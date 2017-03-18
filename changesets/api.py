from flask import Flask, jsonify
from flask.json import JSONEncoder
from changesets.backfiller import process_changeset
import datetime


class CustomJSONEncoder(JSONEncoder):

    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        else:
            return JSONEncoder.default(self, obj)


app = Flask(__name__)
app.json_encoder = CustomJSONEncoder


@app.route('/changesets/<int:changeset_id>')
def full_changeset(changeset_id):
    result = process_changeset(changeset_id)
    return jsonify(result)


if __name__ == '__main__':
    app.run()
