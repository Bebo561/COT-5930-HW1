import os
import uuid
from flask import Flask, render_template, request, jsonify
from google.cloud import storage
from google.auth import credentials
from dotenv import load_dotenv

load_dotenv()

# Retrieve the bucket_name from environment variables
bucket_name = os.getenv("BUCKET_NAME")

# Create necessary local folder
os.makedirs("files", exist_ok=True)

app = Flask(__name__)

# Initialize Google Cloud Storage client
storage_client = storage.Client.create_anonymous_client()

@app.route("/")
def index():
    """Render the homepage."""
    return render_template("home.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "image" not in request.files:
        return jsonify({"error": "No image file in the request"}), 400
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        # Generate a unique filename
        unique_filename = f"{uuid.uuid4()}_{file.filename}"

        # Upload the file to Google Cloud Storage
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(unique_filename)
        blob.upload_from_file(file, content_type=file.content_type)

        return jsonify({
            "filename": unique_filename,
            "upload_status": "Success",
            "url": blob.public_url
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/files", methods=["GET"])
def list_files():
    """List all files in the bucket."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blobs = bucket.list_blobs()
        files = [{"name": blob.name, "url": blob.public_url} for blob in blobs]
        return jsonify({"files": files}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/files/<filename>", methods=["GET"])
def get_file(filename):
    """Get details of a specific file."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        if not blob.exists():
            return jsonify({"error": "File not found"}), 404

        return jsonify({
            "name": blob.name,
            "size": blob.size,
            "content_type": blob.content_type,
            "url": blob.public_url
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
