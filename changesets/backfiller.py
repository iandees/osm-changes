import argparse
import datetime
import errno
import json
import logging
import os
import sys
from collections import OrderedDict
from lxml import etree
from pyosm.api import Api
from pyosm import model


a = Api()

logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
logger = logging.getLogger('osm')


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, datetime.datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def node_version_at_time(node_id, ts):
    logger.info("Fetching node id %s history for timestamp %s", node_id, ts.isoformat())
    node_history = a.get_node_history(node_id)

    version_to_use = None
    for version in node_history:
        if version.timestamp <= ts:
            version_to_use = version
        else:
            break

    return version_to_use


def way_version_at_time(way_id, ts):
    logger.info("Fetching way id %s history for timestamp %s", way_id, ts.isoformat())
    way_history = a.get_way_history(way_id)

    version_to_use = None
    for version in way_history:
        if version.timestamp <= ts:
            version_to_use = version
        else:
            break

    return version_to_use


def thing_to_element(thing):
    if isinstance(thing, model.Node):
        thing_elem = etree.Element("node")
    elif isinstance(thing, model.Way):
        thing_elem = etree.Element("way")
    elif isinstance(thing, model.Relation):
        thing_elem = etree.Element("relation")

    thing_elem.attrib["id"] = str(thing.id)
    thing_elem.attrib["version"] = str(thing.version)
    thing_elem.attrib["changeset"] = str(thing.changeset)
    thing_elem.attrib["user"] = thing.user
    thing_elem.attrib["uid"] = str(thing.uid)
    thing_elem.attrib["timestamp"] = thing.timestamp.isoformat() + "Z"

    for tag in thing.tags:
        thing_elem.append(etree.Element("tag", k=tag.key, v=tag.value))

    if isinstance(thing, model.Node):
        if thing.lat:
            thing_elem.attrib['lat'] = str(thing.lat)
        if thing.lon:
            thing_elem.attrib['lon'] = str(thing.lon)

    elif isinstance(thing, model.Way):
        for nd in thing.nds:
            node_version = node_version_at_time(nd, thing.timestamp)

            # logger.info("Picked node/%s/%s for way/%s/%s",
            #     node_version.id,
            #     node_version.version,
            #     thing.id,
            #     thing.version,
            #     thing.timestamp.isoformat()
            # )

            thing_elem.append(etree.Element("nd", ref=str(nd), lat=str(node_version.lat), lon=str(node_version.lon)))

    elif isinstance(thing, model.Relation):
        for member in thing.members:
            member_elem = etree.Element("member", type=member.type, ref=str(member.ref), role=member.role)

            if member.type == 'node':
                node_version = node_version_at_time(member.ref, thing.timestamp)
                member_elem.attrib['lat'] = str(node_version.lat)
                member_elem.attrib['lon'] = str(node_version.lon)
            elif member.type == 'way':
                way_version = way_version_at_time(member.ref, thing.timestamp)
                for nd in way_version.nds:
                    node_version = node_version_at_time(nd, way_version.timestamp)
                    thing_elem.append(etree.Element("nd", ref=str(nd), lat=str(node_version.lat), lon=str(node_version.lon)))
            elif member.type == 'relation':
                logger.warn("Not fetching relation parts for member relation")
                pass

            thing_elem.append(member_elem)

    return thing_elem


def get_osm_object(typ, id, version):
    if isinstance(typ, model.Node):
        t = 'n'
        data = a.get_node(id, version)
    elif isinstance(typ, model.Way):
        t = 'w'
        data = a.get_way(id, version)
    elif isinstance(typ, model.Relation):
        t = 'r'
        data = a.get_relation(id, version)

    output = OrderedDict([
        ('id', data.id),
        ('version', data.version),
        ('timestamp', data.timestamp),
        ('changeset', data.changeset),
        ('visible', data.visible),
        ('user', data.user),
        ('uid', data.uid),
        ('tags', dict([(tag.key, tag.value) for tag in data.tags])),
    ])

    def get_geom_at_timestamp(nodes, timestamp):
        lat_lons = []
        for nd in nodes:
            v = node_version_at_time(nd, timestamp)
            lat_lons.append((v.lon, v.lat))

        return lat_lons

    if t == 'n':
        output['lat'] = data.lat
        output['lon'] = data.lon
    elif t == 'w':
        output['nodes'] = data.nds
        output['geometry'] = get_geom_at_timestamp(data.nds, data.timestamp)
    elif t == 'r':
        output['members'] = []
        for member in data['members']:
            backfilled_member = OrderedDict([
                ('type', member['type']),
                ('ref', member['ref']),
                ('role', member['role']),
            ])

            if member['type'] == 'way':
                way = way_version_at_time(member['ref'], data['timestamp'])
                linestring = get_geom_at_timestamp(way['nodes'], data['timestamp'])
                backfilled_member['geometry'] = linestring

            output['members'].append(backfilled_member)

    return output


def process_changeset(changeset_id):
    changeset = a.get_changeset_metadata(changeset_id)
    changeset_changes = a.get_changeset_download(changeset_id)

    changeset_meta_dict = OrderedDict([
        ("id", changeset.id),
        ("user", changeset.user),
        ("uid", changeset.uid),
        ("created_at", changeset.created_at.isoformat()),
        ("closed_at", changeset.closed_at.isoformat()),
        ("open", changeset.open),
        ("min_lat", changeset.min_lat),
        ("min_lon", changeset.min_lon),
        ("max_lat", changeset.max_lat),
        ("max_lon", changeset.max_lon),
        ("tags", dict([(t.key, t.value) for t in changeset.tags])),
    ])

    output = OrderedDict([
        ('meta', {
            "version": "0.6",
            "generator": "pyosm",
            "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."
        }),
        ('changeset', changeset_meta_dict),
        ('changes', []),
    ])

    for verb, obj in changeset_changes:
        change_parts = []
        if verb in ('modify', 'delete'):
            old_obj = get_osm_object(obj, obj.id, obj.version - 1)
            change_parts.append(('old', old_obj))

        new_obj = get_osm_object(obj, obj.id, obj.version)
        change_parts.append(('new', new_obj))

        change = OrderedDict(change_parts)

        output['changes'].append(change)

    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('changeset_id', type=int,
                        help='The changeset ID to use')
    args = parser.parse_args()

    result = process_changeset(args.changeset_id)

    filename = '{}/{}.json'.format('.', args.changeset_id)
    with open(filename, 'w') as f:
        json.dump(result, f, indent=4, default=json_serial)
        logger.info("Wrote out %s", filename)
