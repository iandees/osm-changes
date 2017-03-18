from flask import Flask, jsonify
from changesets.backfiller import process_changeset


app = Flask(__name__)


@app.route('/changesets/<int:changeset_id>')
def full_changeset(changeset_id):
    result = process_changeset(changeset_id)
    return jsonify(result)


if __name__ == '__main__':
    app.run()
