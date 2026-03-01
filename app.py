from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from skimage.metrics import structural_similarity as ssim
import cv2
import os
import uuid

# ================= APP =================
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})

# SocketIO (Render safe mode)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ================= DATABASE =================
database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL environment variable not set!")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ================= UPLOAD =================
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ================= MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    status = db.Column(db.String(20))
    user_id = db.Column(db.Integer)
    image_filename = db.Column(db.String(300))
    matched = db.Column(db.Boolean, default=False)

# ================= IMAGE MATCH =================
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

# ================= STATIC ROUTES =================
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/login.html")
def login_page():
    return app.send_static_file("login.html")

@app.route("/register.html")
def register_page():
    return app.send_static_file("register.html")

@app.route("/dashboard.html")
def dashboard_page():
    return app.send_static_file("dashboard.html")

# ================= REGISTER =================
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    if not data:
        return jsonify({"message": "Invalid data"}), 400

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not name or not email or not password:
        return jsonify({"message": "All fields required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"message": "Email already exists"}), 400

    hashed_password = generate_password_hash(password)

    new_user = User(
        name=name,
        email=email,
        password=hashed_password
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "Registered successfully"}), 200

# ================= LOGIN =================
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    if not data:
        return jsonify({"message": "Invalid data"}), 400

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

# ================= GET MY ITEMS =================
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

# ================= UPLOAD =================
@app.route("/upload", methods=["POST"])
def upload():
    title = request.form.get("title")
    description = request.form.get("description")
    status = request.form.get("status")
    user_id = request.form.get("user_id")
    image = request.files.get("image")

    if not title or not description or not status or not user_id:
        return jsonify({"message": "All fields required"}), 400

    if not image:
        return jsonify({"message": "Image required"}), 400

    try:
        user_id = int(user_id)
    except:
        return jsonify({"message": "Invalid user ID"}), 400

    filename = str(uuid.uuid4()) + "_" + secure_filename(image.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    image.save(filepath)

    new_item = Item(
        title=title,
        description=description,
        status=status,
        user_id=user_id,
        image_filename=filename
    )

    db.session.add(new_item)
    db.session.commit()

    # AI MATCH
    opposite = "found" if status == "lost" else "lost"
    items = Item.query.filter_by(status=opposite, matched=False).all()

    for item in items:
        if item.user_id == user_id:
            continue

        other_path = os.path.join(app.config["UPLOAD_FOLDER"], item.image_filename)

        similarity = calculate_image_similarity(filepath, other_path)

        if similarity >= 0.85:
            new_item.matched = True
            item.matched = True
            db.session.commit()

            socketio.emit("match_found", {
                "user1": user_id,
                "user2": item.user_id
            })

            return jsonify({
                "message": "🔥 MATCH FOUND!",
                "similarity": round(similarity * 100, 2)
            })

    return jsonify({"message": "Item uploaded successfully"})

# ================= DELETE =================
@app.route("/delete/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    item = db.session.get(Item, item_id)

    if not item:
        return jsonify({"message": "Item not found"}), 404

    db.session.delete(item)
    db.session.commit()

    return jsonify({"message": "Deleted successfully"})

# ================= SERVE UPLOADS =================
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ================= START =================
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port)
