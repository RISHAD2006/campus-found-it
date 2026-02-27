from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from skimage.metrics import structural_similarity as ssim
import cv2
import os
import uuid

app = Flask(__name__)
CORS(app)

# ================= DATABASE =================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================= MAIL CONFIG =================
app.config['MAIL_SERVER'] = 'smtp.sendgrid.net'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'apikey'
app.config['MAIL_PASSWORD'] = os.environ.get("SENDGRID_API_KEY")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_DEFAULT_SENDER")

mail = Mail(app)

# ================= UPLOAD =================
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ================= MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    status = db.Column(db.String(20))
    user_id = db.Column(db.Integer)
    image_filename = db.Column(db.String(300))
    matched = db.Column(db.Boolean, default=False)

# ================= IMAGE SIMILARITY =================
def calculate_image_similarity(img1_path, img2_path):
    img1 = cv2.imread(img1_path)
    img2 = cv2.imread(img2_path)

    if img1 is None or img2 is None:
        return 0

    img1 = cv2.resize(img1, (300, 300))
    img2 = cv2.resize(img2, (300, 300))

    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    score, _ = ssim(gray1, gray2, full=True)
    return score

@app.route("/")
def home():
    return "AI Matching System Running 🚀"

# ================= REGISTER =================
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"message": "Email already exists"}), 400

    user = User(
        name=data["name"],
        email=data["email"],
        password=generate_password_hash(data["password"])
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Registered successfully"})

# ================= LOGIN =================
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data["email"]).first()

    if not user:
        return jsonify({"message": "User not found"}), 404

    if not check_password_hash(user.password, data["password"]):
        return jsonify({"message": "Incorrect password"}), 401

    return jsonify({
        "message": "Login successful",
        "user_id": user.id,
        "name": user.name,
        "email": user.email
    })

# ================= UPLOAD + MATCH =================
@app.route("/upload", methods=["POST"])
def upload_item():
    title = request.form.get("title")
    description = request.form.get("description")
    status = request.form.get("status")
    user_id = int(request.form.get("user_id"))
    image = request.files.get("image")

    if not image:
        return jsonify({"error": "Image required"}), 400

    filename = str(uuid.uuid4()) + "_" + secure_filename(image.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    image.save(path)

    new_item = Item(
        title=title,
        description=description,
        status=status,
        user_id=user_id,
        image_filename=filename
    )

    db.session.add(new_item)
    db.session.commit()

    opposite = "found" if status == "lost" else "lost"
    items = Item.query.filter_by(status=opposite, matched=False).all()

    for item in items:
        if item.user_id == user_id:
            continue

        other_path = os.path.join(app.config["UPLOAD_FOLDER"], item.image_filename)
        similarity = calculate_image_similarity(path, other_path)

        if similarity >= 0.85:
            new_item.matched = True
            item.matched = True
            db.session.commit()

            return jsonify({
                "message": "🔥 MATCH FOUND!",
                "similarity": round(similarity * 100, 2)
            })

    return jsonify({"message": "Item uploaded successfully"})
