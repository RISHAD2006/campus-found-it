from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from flask_socketio import SocketIO
from skimage.metrics import structural_similarity as ssim
import cv2
import os
import uuid

app = Flask(__name__)
CORS(app)

# =========================
# SOCKET IO (Phase 3)
# =========================
socketio = SocketIO(app, cors_allowed_origins="*")

# =========================
# DATABASE CONFIG
# =========================
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# =========================
# EMAIL CONFIG
# =========================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'rishadrichu0580@gmail.com'
app.config['MAIL_PASSWORD'] = 'srgqgjongcanojba'
app.config['MAIL_DEFAULT_SENDER'] = 'rishadrichu0580@gmail.com'

mail = Mail(app)

# =========================
# UPLOAD FOLDER
# =========================
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# =========================
# MODELS
# =========================

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

# =========================
# IMAGE SIMILARITY (SSIM)
# =========================

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

# =========================
# HOME
# =========================

@app.route("/")
def home():
    return "AI Matching System Running 🚀"

# =========================
# REGISTER (SECURE)
# =========================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json()

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if User.query.filter_by(email=email).first():
        return jsonify({"message": "Email already exists"}), 400

    hashed_password = generate_password_hash(password)

    user = User(
        name=name,
        email=email,
        password=hashed_password
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Registered successfully"})

# =========================
# LOGIN (SECURE)
# =========================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({"message": "User not found"}), 404

    if not check_password_hash(user.password, password):
        return jsonify({"message": "Incorrect password"}), 401

    return jsonify({
        "message": "Login successful",
        "user_id": user.id,
        "name": user.name,
        "email": user.email
    })
# =========================
# UPLOAD + MATCH + EMAIL + LIVE ALERT
# =========================

@app.route("/upload", methods=["POST"])
def upload_item():

    title = request.form.get("title")
    description = request.form.get("description")
    status = request.form.get("status")
    user_id = request.form.get("user_id")
    image = request.files.get("image")

    if not title or not description or not image or not user_id:
        return jsonify({"error": "Missing fields"}), 400

    user_id = int(user_id)

    unique_name = str(uuid.uuid4()) + "_" + secure_filename(image.filename)
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
    image.save(image_path)

    new_item = Item(
        title=title,
        description=description,
        status=status,
        user_id=user_id,
        image_filename=unique_name,
        matched=False
    )

    db.session.add(new_item)
    db.session.commit()

    opposite_status = "found" if status == "lost" else "lost"

    candidates = Item.query.filter_by(
        status=opposite_status,
        matched=False
    ).all()

    for item in candidates:

        if item.user_id == user_id:
            continue

        other_image_path = os.path.join(app.config["UPLOAD_FOLDER"], item.image_filename)

        similarity = calculate_image_similarity(image_path, other_image_path)

        print("Similarity:", similarity)

        if similarity >= 0.85:

            new_item.matched = True
            item.matched = True
            db.session.commit()

            user1 = db.session.get(User, new_item.user_id)
            user2 = db.session.get(User, item.user_id)

            # 🔔 REAL-TIME MATCH EVENT
            socketio.emit("match_found", {
                "message": "🔥 MATCH FOUND!",
                "user1": user1.id,
                "user2": user2.id
            })

            # 📧 EMAIL
            if user1 and user2:
                try:
                    msg1 = Message(
                        "🔥 Your Item Has Been Matched!",
                        recipients=[user1.email]
                    )
                    msg1.body = f"""
Good news!

Your item '{new_item.title}' has been matched.

Contact: {user2.email}

Campus Found-It AI
"""
                    mail.send(msg1)

                    msg2 = Message(
                        "🔥 Your Item Has Been Matched!",
                        recipients=[user2.email]
                    )
                    msg2.body = f"""
Good news!

Your item '{item.title}' has been matched.

Contact: {user1.email}

Campus Found-It AI
"""
                    mail.send(msg2)

                    print("✅ Email sent successfully!")

                except Exception as e:
                    print("❌ Email Error:", e)

            return jsonify({
                "message": "🔥 MATCH FOUND!",
                "similarity": round(similarity * 100, 2)
            })

    return jsonify({"message": "Item uploaded successfully"})

# =========================
# MY ITEMS
# =========================

@app.route("/my-items/<int:user_id>")
def my_items(user_id):

    items = Item.query.filter_by(user_id=user_id).all()

    result = []

    for item in items:
        result.append({
            "id": item.id,
            "title": item.title,
            "description": item.description,
            "status": item.status,
            "matched": item.matched,
            "image_url": f"http://127.0.0.1:5000/uploads/{item.image_filename}"
        })

    return jsonify(result)

# =========================
# DELETE
# =========================

@app.route("/delete/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):

    item = db.session.get(Item, item_id)

    if not item:
        return jsonify({"error": "Item not found"}), 404

    image_path = os.path.join(app.config["UPLOAD_FOLDER"], item.image_filename)

    if os.path.exists(image_path):
        os.remove(image_path)

    db.session.delete(item)
    db.session.commit()

    return jsonify({"message": "Deleted successfully"})

# =========================
# SERVE IMAGE
# =========================

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# =========================
# RUN
# =========================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    socketio.run(app, host="0.0.0.0", port=10000)