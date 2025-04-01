from flask import Flask, request, render_template, jsonify, session, flash
from werkzeug.utils import secure_filename
from io import BytesIO
from google.cloud import storage, datastore
from dotenv import load_dotenv
import uuid
import os
import base64
import requests
import datetime
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = '89c25124aeaafe4fdcf01a2724187847'  # Change this in production!

# Google Cloud setup
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./key.json"
bucket_name = os.getenv("BUCKET_NAME")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  

# Initialize Google Cloud clients
storage_client = storage.Client()
datastore_client = datastore.Client()

def get_blob_name_from_url(url):
    """Extract blob name from a GCS URL."""
    if f"{bucket_name}/" in url:
        return url.split(f"{bucket_name}/")[1]
    return url  # If URL format is unexpected, return as-is

def generate_signed_url(blob_name, expiration=3600):
    """Generate a temporary signed URL for a GCS blob."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration),
        method="GET"
    )

def get_image_metadata(image_data):
    """Uses Gemini AI to generate a title and description for an image."""
    encoded_image = base64.b64encode(image_data).decode('utf-8')
    
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [
                {"text": "Provide a short title (5-10 words) and a brief description (1-2 sentences) for this image. Format your response as: Title: [title] Description: [description]"},
                {"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}}
            ]
        }]
    }
    
    response = requests.post(url, headers=headers, json=payload, params={'key': GEMINI_API_KEY})
    result = response.json()
    
    try:
        text_response = result['candidates'][0]['content']['parts'][0]['text']
        title, description = "Untitled Image", "No description available"
        
        if "Title:" in text_response and "Description:" in text_response:
            title = text_response.split("Title:")[1].split("Description:")[0].strip()
            description = text_response.split("Description:")[1].strip()
        else:
            lines = text_response.strip().split('\n')
            title, description = (lines[0], ' '.join(lines[1:])) if len(lines) > 1 else ("Untitled Image", "No description available")
        
        return {"title": title, "description": description}
    
    except (KeyError, IndexError) as e:
        print(f"Metadata extraction error: {e}")
        return {"title": "Untitled Image", "description": "No description available"}

@app.route('/files')
def gallery():
    """Returns a JSON list of uploaded images with signed URLs and metadata."""
    query = datastore_client.query(kind='images')
    query.add_filter('useremail', '=', session['user_email'])
    images = list(query.fetch())

    bucket = storage_client.bucket(bucket_name)
    files = []

    for image in images:
        blob_name = image.get('blob_name') or get_blob_name_from_url(image.get('imagelink', ''))
        
        if not blob_name:
            continue

        signed_url = generate_signed_url(blob_name)
        image_data = {
            "name": image.get("blob_name", "Unknown"),
            "url": signed_url,
            "title": "Untitled Image",
            "description": "No description available"
        }
        
        # Fetch metadata if available
        json_blob = bucket.blob(f"{os.path.splitext(blob_name)[0]}.json")
        if json_blob.exists():
            try:
                metadata = json.loads(json_blob.download_as_string())
                image_data.update(metadata)
            except json.JSONDecodeError:
                pass  # Keep default title and description
        
        files.append(image_data)

    return jsonify({"files": files})

@app.route('/', methods=["GET"])
def home():
    return render_template('home.html')

@app.route('/upload-image', methods=['POST'])
def upload_image():
    """Handles image upload and metadata generation."""
    file = request.files.get('image')
    print("File received:", file)
    
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        unique_filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        base_filename = os.path.splitext(unique_filename)[0]
        image_data = file.read()
        
        # Get metadata from image
        metadata = get_image_metadata(image_data)
        
        # Upload to Google Cloud Storage
        bucket = storage_client.bucket(bucket_name)
        
        # Upload image
        image_blob = bucket.blob(unique_filename)
        image_blob.upload_from_file(
            BytesIO(image_data), 
            content_type=file.content_type
        )
        
        # Generate public URL for the image
        image_url = image_blob.public_url
        
        # Upload metadata as JSON
        json_blob = bucket.blob(f"{base_filename}.json")
        json_blob.upload_from_string(
            json.dumps(metadata), 
            content_type="application/json"
        )
        
        # Store in Datastore
        entity = datastore.Entity(key=datastore_client.key('images'))
        entity.update({
            'useremail': session['user_email'],
            'blob_name': unique_filename,
            'image_url': image_url,  # Store the URL
            **metadata,
            'upload_date': datetime.datetime.now()
        })
        datastore_client.put(entity)
        
        # Return success JSON response instead of redirect
        return jsonify({
            "success": True,
            "message": "File uploaded successfully",
            "filename": unique_filename,
            "url": image_url
        }), 200
        
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
