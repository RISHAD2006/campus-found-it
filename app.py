from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from skimage.metrics import structural_similarity as ssim
import cv2
import os
import uuid

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ================= DATABASE =================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///campus.db"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ================= MAIL CONFIG =================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# ================= UPLOAD =================
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

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

# ================= HOME =================
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

# ================= UPLOAD + AI MATCH + EMAIL =================
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

            user1 = db.session.get(User, user_id)
            user2 = db.session.get(User, item.user_id)

            socketio.emit("match_found", {
                "user1": user1.id,
                "user2": user2.id
            })

            try:
                msg1 = Message(
                    "🔥 Lost Item Matched!",
                    recipients=[user1.email]
                )
                msg1.body = f"""
Good News!

Your item '{new_item.title}' has been matched.

Contact: {user2.email}

Campus Found-It
"""
                mail.send(msg1)

                msg2 = Message(
                    "🔥 Found Item Matched!",
                    recipients=[user2.email]
                )
                msg2.body = f"""
Good News!

Your item '{item.title}' has been matched.

Contact: {user1.email}

Campus Found-It
"""
                mail.send(msg2)

                print("✅ Emails sent successfully!")

            except Exception as e:
                print("❌ Email Error:", e)

            return jsonify({
                "message": "🔥 MATCH FOUND!",
                "similarity": round(similarity * 100, 2)
            })

    return jsonify({"message": "Item uploaded successfully"})

# ================= MY ITEMS =================
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
            "image_url": request.host_url + "uploads/" + item.image_filename
        })

    return jsonify(result)

# ================= DELETE =================
@app.route("/delete/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    item = db.session.get(Item, item_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404

    db.session.delete(item)
    db.session.commit()

    return jsonify({"message": "Deleted successfully"})

# ================= SERVE IMAGE =================
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ================= START =================
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)
