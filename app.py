import os
import re
import math
import uuid
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, abort
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Text, Integer, Float, ForeignKey, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, IntegerField, SelectField, RadioField
from wtforms.validators import DataRequired, Optional, NumberRange, ValidationError
from werkzeug.utils import secure_filename

# =========================================================
# CẤU HÌNH ỨNG DỤNG & CSDL SQLITE (CHƯƠNG 6)
# =========================================================
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
csrf = CSRFProtect()

app = Flask(__name__)
app.config["SECRET_KEY"] = "nha-sach-song-huong-secret-key-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///nhasach.db"
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # Cho phép request lớn để kiểm tra kích thước ảnh trong form

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)
csrf.init_app(app)


# =========================================================
# KHAI BÁO MODELS (SQLALCHEMY 2.0)
# =========================================================
class Category(db.Model):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(255), default="")

    books: Mapped[list["Book"]] = relationship(back_populates="category")

    def __repr__(self):
        return f"<Category {self.id} {self.name}>"


class Book(db.Model):
    __tablename__ = "book"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150), unique=True)
    author: Mapped[str] = mapped_column(String(100))
    publisher: Mapped[str | None] = mapped_column(String(120), default="NXB Đại học Huế")
    publish_year: Mapped[int | None] = mapped_column(Integer, default=2024)
    price: Mapped[int] = mapped_column(Integer, default=1000)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, default="")
    cover_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))

    category: Mapped["Category"] = relationship(back_populates="books")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="book")

    def __repr__(self):
        return f"<Book {self.id} {self.title}>"


class Order(db.Model):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(20))
    customer_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_address: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_method: Mapped[str] = mapped_column(String(50), default="Tiền mặt khi nhận hàng")
    subtotal: Mapped[int] = mapped_column(Integer, default=0)
    shipping_fee: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="Chờ xác nhận")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    logs: Mapped[list["OrderLog"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLog.id"
    )


class OrderItem(db.Model):
    __tablename__ = "order_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped["Order"] = relationship(back_populates="items")
    book: Mapped["Book"] = relationship(back_populates="order_items")

    @property
    def line_total(self) -> int:
        return self.quantity * self.unit_price


class OrderLog(db.Model):
    __tablename__ = "order_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    order: Mapped["Order"] = relationship(back_populates="logs")


# =========================================================
# FILTERS & CONTEXT PROCESSORS (CHƯƠNG 4 & 5)
# =========================================================
@app.template_filter("vnd")
def format_vnd(value):
    try:
        val = int(round(float(value)))
        return f"{val:,}".replace(",", ".") + " đ"
    except (ValueError, TypeError):
        return "0 đ"


@app.template_filter("vnd_no_symbol")
def format_vnd_no_symbol(value):
    try:
        val = int(round(float(value)))
        return f"{val:,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


@app.context_processor
def inject_global_data():
    # Tính tổng số lượng sách trong giỏ hàng từ session
    cart = session.get("cart", {})
    cart_total_qty = sum(int(qty) for qty in cart.values() if str(qty).isdigit())

    # Đếm số đơn hàng "Chờ xác nhận" cho menu Quản trị
    pending_orders_count = db.session.scalar(
        db.select(func.count(Order.id)).where(Order.status == "Chờ xác nhận")
    ) or 0

    return dict(
        cart_total_qty=cart_total_qty,
        pending_orders_count=pending_orders_count,
    )


# =========================================================
# FLASK-WTF FORMS (CHƯƠNG 5)
# =========================================================
class CheckoutForm(FlaskForm):
    customer_name = StringField(
        "Họ tên *",
        validators=[DataRequired(message="Vui lòng nhập họ tên người nhận.")],
    )
    customer_phone = StringField(
        "Số điện thoại *",
        validators=[DataRequired(message="Vui lòng nhập số điện thoại.")],
    )
    customer_email = StringField("Email", validators=[Optional()])
    shipping_address = StringField(
        "Địa chỉ giao hàng *",
        validators=[DataRequired(message="Vui lòng nhập địa chỉ giao hàng.")],
    )
    note = StringField("Ghi chú", validators=[Optional()])
    payment_method = RadioField(
        "Thanh toán *",
        choices=[
            ("Tiền mặt khi nhận hàng", "Tiền mặt khi nhận hàng"),
            ("Chuyển khoản", "Chuyển khoản"),
        ],
        default="Tiền mặt khi nhận hàng",
        validators=[DataRequired(message="Vui lòng chọn hình thức thanh toán.")],
    )

    def validate_customer_phone(self, field):
        phone = (field.data or "").strip()
        if not re.fullmatch(r"0\d{9}", phone):
            raise ValidationError("Số điện thoại gồm 10 chữ số và bắt đầu bằng số 0.")

    def validate_customer_email(self, field):
        email = (field.data or "").strip()
        if email:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ValidationError("Địa chỉ email không đúng định dạng.")


class BookForm(FlaskForm):
    title = StringField(
        "Tên sách *",
        validators=[DataRequired(message="Vui lòng nhập tên sách.")],
    )
    author = StringField(
        "Tác giả *",
        validators=[DataRequired(message="Vui lòng nhập tên tác giả.")],
    )
    category_id = SelectField(
        "Danh mục *",
        coerce=int,
        validators=[DataRequired(message="Vui lòng chọn danh mục.")],
    )
    publish_year = IntegerField(
        "Năm xuất bản",
        validators=[Optional()],
    )
    publisher = StringField("Nhà xuất bản", validators=[Optional()])
    price = IntegerField(
        "Giá (đồng) *",
        validators=[DataRequired(message="Vui lòng nhập giá sách.")],
    )
    stock = IntegerField(
        "Tồn kho *",
        validators=[],
    )
    description = TextAreaField("Mô tả", validators=[Optional()])
    cover_file = FileField(
        "Ảnh bìa",
        validators=[
            FileAllowed(["jpg", "jpeg", "png", "webp"], "Chỉ chấp nhận ảnh JPG, PNG, WEBP.")
        ],
    )

    def __init__(self, edit_book_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.edit_book_id = edit_book_id

    def validate_title(self, field):
        title_clean = (field.data or "").strip()
        if not title_clean:
            raise ValidationError("Vui lòng nhập tên sách.")
        stmt = db.select(Book).where(func.lower(Book.title) == title_clean.lower())
        if self.edit_book_id is not None:
            stmt = stmt.where(Book.id != self.edit_book_id)
        existing = db.session.scalar(stmt)
        if existing:
            raise ValidationError("Tên sách đã tồn tại.")

    def validate_price(self, field):
        if field.data is None or field.data < 1000:
            raise ValidationError("Giá sách phải từ 1.000 đồng trở lên.")

    def validate_stock(self, field):
        raw = request.form.get("stock", "").strip()
        if raw == "":
            raise ValidationError("Vui lòng nhập số lượng tồn kho.")
        try:
            val = int(raw)
        except ValueError:
            raise ValidationError("Tồn kho phải là số nguyên.")
        if val < 0:
            raise ValidationError("Tồn kho không âm.")
        field.data = val

    def validate_publish_year(self, field):
        current_year = datetime.now().year
        if field.data is not None:
            if field.data < 1900 or field.data > current_year:
                raise ValidationError(f"Năm xuất bản phải từ 1900 đến {current_year}.")

    def validate_cover_file(self, field):
        file = field.data
        if file and getattr(file, "filename", ""):
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > 2 * 1024 * 1024:
                raise ValidationError("Kích thước ảnh tối đa 2 MB.")


class CategoryForm(FlaskForm):
    name = StringField(
        "Tên *",
        validators=[DataRequired(message="Vui lòng nhập tên danh mục.")],
    )
    description = TextAreaField("Mô tả", validators=[Optional()])

    def __init__(self, edit_cat_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.edit_cat_id = edit_cat_id

    def validate_name(self, field):
        name_clean = (field.data or "").strip()
        if not name_clean:
            raise ValidationError("Vui lòng nhập tên danh mục.")
        stmt = db.select(Category).where(func.lower(Category.name) == name_clean.lower())
        if self.edit_cat_id is not None:
            stmt = stmt.where(Category.id != self.edit_cat_id)
        existing = db.session.scalar(stmt)
        if existing:
            raise ValidationError("Danh mục đã tồn tại.")


# =========================================================
# HÀM HỖ TRỢ GIỎ HÀNG & DỮ LIỆU MẪU
# =========================================================
def get_cart_details():
    """Đọc session['cart'] và lấy giá mới nhất từ CSDL."""
    cart = session.get("cart", {})
    items = []
    subtotal = 0
    updated_cart = {}

    for book_id_str, qty in cart.items():
        try:
            b_id = int(book_id_str)
            quantity = int(qty)
        except (ValueError, TypeError):
            continue

        if quantity <= 0:
            continue

        book = db.session.get(Book, b_id)
        if not book:
            continue

        updated_cart[str(b_id)] = quantity
        line_total = book.price * quantity
        subtotal += line_total
        items.append({
            "book": book,
            "quantity": quantity,
            "unit_price": book.price,
            "line_total": line_total,
        })

    if updated_cart != cart:
        session["cart"] = updated_cart

    shipping_fee = 0 if (subtotal >= 200000 or subtotal == 0) else 20000
    total_amount = subtotal + shipping_fee
    return items, subtotal, shipping_fee, total_amount


def seed_initial_data():
    """Khởi tạo dữ liệu mẫu đúng theo các màn hình trong đề bài."""
    if (db.session.scalar(db.select(func.count(Category.id))) or 0) > 0:
        return

    cat_lt = Category(name="Lập trình", description="Sách ngôn ngữ lập trình và phát triển phần mềm")
    cat_csdl = Category(name="Cơ sở dữ liệu", description="Sách hệ quản trị CSDL, SQL và thiết kế dữ liệu")
    cat_cc = Category(name="Công cụ", description="Sách quản lý mã nguồn Git, Docker và công cụ phát triển")
    cat_mang = Category(name="Mạng", description="Sách mạng máy tính, giao thức truyền thông và an ninh mạng")
    cat_kn = Category(name="Kỹ năng lập trình", description="Sách tư duy thiết kế, kiến trúc phần mềm và Clean Code")
    cat_tk = Category(name="Thiết kế", description="Sách thiết kế giao diện UI/UX và đồ hoạ")

    db.session.add_all([cat_lt, cat_csdl, cat_cc, cat_mang, cat_kn, cat_tk])
    db.session.flush()

    b1 = Book(
        title="Lập trình Python cơ bản",
        author="Nguyễn Văn A",
        publisher="NXB Đại học Huế",
        publish_year=2024,
        price=95000,
        stock=28,
        description="Giáo trình nhập môn lập trình Python từ cơ bản đến nâng cao dành cho sinh viên CNTT.",
        category_id=cat_lt.id,
    )
    b2 = Book(
        title="Giáo trình Flask",
        author="Miguel Grinberg",
        publisher="NXB Khoa học Kỹ thuật",
        publish_year=2023,
        price=120000,
        stock=19,
        description="Hướng dẫn xây dựng ứng dụng web thực tế với micro-framework Flask, Jinja2 và SQLAlchemy.",
        category_id=cat_lt.id,
    )
    b3 = Book(
        title="Cơ sở dữ liệu",
        author="Trần Văn B",
        publisher="NXB Đại học Huế",
        publish_year=2022,
        price=85000,
        stock=0,
        description="Nguyên lý hệ cơ sở dữ liệu quan hệ, đại số quan hệ và ngôn ngữ truy vấn SQL.",
        category_id=cat_csdl.id,
    )
    b4 = Book(
        title="Pro Git",
        author="Scott Chacon",
        publisher="NXB Thế Giới",
        publish_year=2021,
        price=150000,
        stock=14,
        description="Cẩm nang toàn diện về quản lý phiên bản phân tán với Git và quy trình làm việc nhóm trên GitHub.",
        category_id=cat_cc.id,
    )
    b5 = Book(
        title="Mạng máy tính",
        author="Lê Văn C",
        publisher="NXB Thông tin & Truyền thông",
        publish_year=2023,
        price=110000,
        stock=12,
        description="Kiến trúc mạng TCP/IP, định tuyến, chuyển mạch và các giao thức mạng hiện đại.",
        category_id=cat_mang.id,
    )
    b6 = Book(
        title="Clean Code",
        author="Robert C. Martin",
        publisher="NXB Trẻ",
        publish_year=2008,
        price=180000,
        stock=5,
        description="Nghệ thuật viết mã nguồn sạch, dễ đọc, dễ bảo trì và mở rộng cho kỹ sư phần mềm.",
        category_id=cat_kn.id,
    )

    db.session.add_all([b1, b2, b3, b4, b5, b6])
    db.session.flush()

    now = datetime.now()
    # Tạo các đơn hàng mẫu để trang Quản trị có đầy đủ số liệu minh họa
    sample_orders_data = [
        # 6 đơn Hoàn tất rải đều trong 7 ngày gần nhất để vẽ biểu đồ & tính doanh thu tháng
        ("Lê Hoàng Cường", "0911222333", "10 Hùng Vương, Huế", "Hoàn tất", now - timedelta(days=6), [(b6, 1, 180000)]),
        ("Đặng Quốc Tuấn", "0912333444", "25 Bà Triệu, Huế", "Hoàn tất", now - timedelta(days=5), [(b1, 2, 95000), (b2, 1, 120000)]),
        ("Ngô Thị Mai", "0913444555", "42 Nguyễn Huệ, Huế", "Hoàn tất", now - timedelta(days=4), [(b4, 1, 150000)]),
        ("Bùi Văn Nam", "0914555666", "18 Đống Đa, Huế", "Hoàn tất", now - timedelta(days=3), [(b5, 2, 110000)]),
        ("Phan Thanh Thảo", "0915666777", "05 Lê Quý Đôn, Huế", "Hoàn tất", now - timedelta(days=2), [(b2, 1, 120000)]),
        ("Trịnh Đình Quang", "0916777888", "88 Điện Biên Phủ, Huế", "Hoàn tất", now - timedelta(days=1), [(b6, 1, 180000), (b1, 1, 95000)]),
        # 1 đơn Đã huỷ
        ("Phạm Minh Dũng", "0935111222", "14 Trần Hưng Đạo, Huế", "Đã huỷ", now - timedelta(days=3, hours=2), [(b1, 1, 75000)]),
        # 2 đơn Đang giao
        ("Huỳnh Ngọc Ánh", "0977888999", "33 Phan Bội Châu, Huế", "Đang giao", now - timedelta(days=2, hours=1), [(b4, 1, 150000), (b5, 1, 110000)]),
        ("Trần Thị Bình", "0905666777", "56 Mai Thúc Loan, Huế", "Đang giao", now - timedelta(days=1, hours=3), [(b1, 1, 95000), (b2, 1, 120000)]),
        # 3 đơn Chờ xác nhận (#10, #11, #12)
        ("Võ Quốc Khánh", "0901234567", "72 Kim Long, Huế", "Chờ xác nhận", now - timedelta(days=2), [(b1, 1, 95000), (b2, 1, 120000)]),
        ("Hoàng Thu Hà", "0987654321", "19 Hai Bà Trưng, Huế", "Chờ xác nhận", now - timedelta(days=1), [(b4, 2, 150000)]),
        ("Nguyễn Văn An", "0912345678", "12 Lê Lợi, phường Thuận Hoá, Huế", "Chờ xác nhận", now - timedelta(hours=2), [(b1, 2, 95000), (b2, 1, 120000), (b4, 1, 150000)]),
    ]

    for cname, cphone, caddr, st, ctime, item_tuples in sample_orders_data:
        sub = sum(q * p for _, q, p in item_tuples)
        ship = 0 if sub >= 200000 else 20000
        tot = sub + ship
        order = Order(
            customer_name=cname,
            customer_phone=cphone,
            customer_email="khachhang@example.com",
            shipping_address=caddr,
            note="Giao giờ hành chính",
            payment_method="Tiền mặt khi nhận hàng",
            subtotal=sub,
            shipping_fee=ship,
            total_amount=tot,
            status=st,
            created_at=ctime,
        )
        db.session.add(order)
        db.session.flush()

        for book_obj, qty, uprice in item_tuples:
            db.session.add(OrderItem(
                order_id=order.id,
                book_id=book_obj.id,
                quantity=qty,
                unit_price=uprice,
            ))

        db.session.add(OrderLog(
            order_id=order.id,
            status="Chờ xác nhận",
            label="Đặt hàng",
            changed_at=ctime,
        ))
        if st in ("Đang giao", "Hoàn tất"):
            db.session.add(OrderLog(
                order_id=order.id,
                status="Đang giao",
                label="Đang giao",
                changed_at=ctime + timedelta(hours=2),
            ))
        if st == "Hoàn tất":
            db.session.add(OrderLog(
                order_id=order.id,
                status="Hoàn tất",
                label="Hoàn tất",
                changed_at=ctime + timedelta(hours=6),
            ))
        if st == "Đã huỷ":
            db.session.add(OrderLog(
                order_id=order.id,
                status="Đã huỷ",
                label="Đã huỷ",
                changed_at=ctime + timedelta(hours=1),
            ))

    db.session.commit()


with app.app_context():
    db.create_all()
    seed_initial_data()


# =========================================================
# PHẦN A. TRANG BÁN HÀNG (MÀN HÌNH 1 -> 5)
# =========================================================

# --- Màn hình 1: Danh sách sách (/ và /books) ---
@app.get("/")
@app.get("/books")
def shop_books():
    q = request.args.get("q", "").strip()
    cat_id_raw = request.args.get("category_id", "").strip()
    selected_cat_id = None

    stmt = db.select(Book).order_by(Book.id)
    if cat_id_raw:
        try:
            selected_cat_id = int(cat_id_raw)
            stmt = stmt.where(Book.category_id == selected_cat_id)
        except ValueError:
            selected_cat_id = None

    if q:
        stmt = stmt.where(
            (Book.title.ilike(f"%{q}%")) | (Book.author.ilike(f"%{q}%"))
        )

    books = db.session.execute(stmt).scalars().all()
    categories = db.session.execute(db.select(Category).order_by(Category.id)).scalars().all()

    return render_template(
        "shop/books.html",
        books=books,
        categories=categories,
        selected_cat_id=selected_cat_id,
        q=q,
    )


# --- Màn hình 2: Chi tiết & Chọn sách (/books/<int:book_id>) ---
@app.get("/books/<int:book_id>")
def shop_book_detail(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        abort(404, description="Không tìm thấy cuốn sách bạn yêu cầu.")

    cart = session.get("cart", {})
    in_cart = int(cart.get(str(book.id), 0))
    max_add = max(0, book.stock - in_cart)

    return render_template(
        "shop/book_detail.html",
        book=book,
        in_cart=in_cart,
        max_add=max_add,
    )


# --- Thêm sách vào giỏ hàng (từ Màn hình 1 hoặc Màn hình 2) ---
@app.post("/cart/add/<int:book_id>")
def cart_add(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        abort(404, description="Sách không tồn tại.")

    next_url = request.form.get("next") or request.referrer or url_for("shop_books")
    qty_raw = request.form.get("quantity", "1").strip()

    try:
        qty = int(qty_raw)
    except ValueError:
        flash("Số lượng thêm vào giỏ không hợp lệ.", "danger")
        return redirect(next_url)

    cart = dict(session.get("cart", {}))
    current_in_cart = int(cart.get(str(book.id), 0))
    max_available = book.stock - current_in_cart

    if book.stock <= 0:
        flash(f'Sách "{book.title}" hiện đã hết hàng.', "danger")
        return redirect(next_url)

    if qty < 1 or qty > max_available:
        flash(
            f'Số lượng không hợp lệ! Tối đa có thể thêm {max_available} cuốn (đã có {current_in_cart} trong giỏ).',
            "danger",
        )
        return redirect(next_url)

    cart[str(book.id)] = current_in_cart + qty
    session["cart"] = cart
    flash(f"✓ Đã thêm {qty} × {book.title} vào giỏ hàng.", "success")
    return redirect(next_url)


# --- Màn hình 3: Giỏ hàng (/cart) ---
@app.get("/cart")
def cart_view():
    items, subtotal, shipping_fee, total_amount = get_cart_details()
    return render_template(
        "shop/cart.html",
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total_amount=total_amount,
    )


@app.post("/cart/update/<int:book_id>")
def cart_update(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        abort(404)

    action = request.form.get("action", "")
    cart = dict(session.get("cart", {}))
    key = str(book_id)
    current_qty = int(cart.get(key, 0))

    if action == "inc":
        if current_qty < book.stock:
            cart[key] = current_qty + 1
            flash(f'Đã tăng số lượng "{book.title}".', "info")
        else:
            flash(f'Số lượng "{book.title}" đã đạt tối đa tồn kho ({book.stock}).', "warning")
    elif action == "dec":
        if current_qty > 1:
            cart[key] = current_qty - 1
            flash(f'Đã giảm số lượng "{book.title}".', "info")
        elif current_qty == 1:
            cart.pop(key, None)
            flash(f'Đã bỏ "{book.title}" khỏi giỏ hàng.', "info")

    session["cart"] = cart
    return redirect(url_for("cart_view"))


@app.post("/cart/remove/<int:book_id>")
def cart_remove(book_id):
    cart = dict(session.get("cart", {}))
    book = db.session.get(Book, book_id)
    cart.pop(str(book_id), None)
    session["cart"] = cart
    if book:
        flash(f'Đã xoá "{book.title}" khỏi giỏ hàng.', "info")
    return redirect(url_for("cart_view"))


@app.post("/cart/clear")
def cart_clear():
    session.pop("cart", None)
    flash("Đã xoá toàn bộ giỏ hàng.", "info")
    return redirect(url_for("cart_view"))


# --- Màn hình 4: Thông tin khách hàng & Đặt hàng (/checkout) ---
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, subtotal, shipping_fee, total_amount = get_cart_details()
    if not items:
        flash("Giỏ hàng đang trống, vui lòng chọn sách trước khi thanh toán.", "warning")
        return redirect(url_for("cart_view"))

    form = CheckoutForm()
    if form.validate_on_submit():
        # Kiểm tra lại tồn kho của từng đầu sách trước khi tạo đơn
        for item in items:
            book = item["book"]
            qty = item["quantity"]
            if qty > book.stock:
                flash(
                    f'Không thể tạo đơn: Sách "{book.title}" chỉ còn {book.stock} cuốn (bạn đặt {qty} cuốn).',
                    "danger",
                )
                return redirect(url_for("cart_view"))

        # Tạo Order trạng thái "Chờ xác nhận"
        now = datetime.now()
        order = Order(
            customer_name=form.customer_name.data.strip(),
            customer_phone=form.customer_phone.data.strip(),
            customer_email=(form.customer_email.data or "").strip() or None,
            shipping_address=form.shipping_address.data.strip(),
            note=(form.note.data or "").strip() or None,
            payment_method=form.payment_method.data,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total_amount=total_amount,
            status="Chờ xác nhận",
            created_at=now,
        )
        db.session.add(order)
        db.session.flush()

        # Tạo các dòng OrderItem (lưu đơn giá lúc đặt) và trừ tồn kho
        for item in items:
            book = item["book"]
            qty = item["quantity"]
            db.session.add(OrderItem(
                order_id=order.id,
                book_id=book.id,
                quantity=qty,
                unit_price=book.price,
            ))
            book.stock -= qty

        # Ghi lịch sử đặt hàng
        db.session.add(OrderLog(
            order_id=order.id,
            status="Chờ xác nhận",
            label="Đặt hàng",
            changed_at=now,
        ))

        db.session.commit()
        session.pop("cart", None)
        flash(f"Đặt hàng thành công! Mã đơn hàng của bạn là #{order.id}.", "success")
        return redirect(url_for("order_success", order_id=order.id))

    return render_template(
        "shop/checkout.html",
        form=form,
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total_amount=total_amount,
    )


# --- Màn hình 5: Đặt hàng thành công (/orders/<int:order_id>) ---
@app.get("/orders/<int:order_id>")
def order_success(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404, description="Không tìm thấy đơn hàng.")
    return render_template("shop/order_success.html", order=order)


# =========================================================
# PHẦN B. TRANG QUẢN TRỊ (/admin - MÀN HÌNH 6 -> 11)
# =========================================================

# --- Màn hình 6: Tổng quan (/admin) ---
@app.get("/admin")
def admin_dashboard():
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)

    # 4 thẻ thống kê, mỗi số là một truy vấn (func.count, func.sum)
    total_books = db.session.scalar(db.select(func.count(Book.id))) or 0
    pending_orders = db.session.scalar(
        db.select(func.count(Order.id)).where(Order.status == "Chờ xác nhận")
    ) or 0
    monthly_revenue = db.session.scalar(
        db.select(func.sum(Order.total_amount)).where(
            Order.status == "Hoàn tất",
            Order.created_at >= month_start,
        )
    ) or 0
    low_stock_count = db.session.scalar(
        db.select(func.count(Book.id)).where(Book.stock <= 5)
    ) or 0

    # 5 đơn hàng mới nhất
    recent_orders = db.session.execute(
        db.select(Order).order_by(Order.id.desc()).limit(5)
    ).scalars().all()

    # Danh sách sách sắp hết hàng (stock <= 5)
    low_stock_books = db.session.execute(
        db.select(Book).where(Book.stock <= 5).order_by(Book.stock.asc(), Book.id.asc())
    ).scalars().all()

    # Biểu đồ doanh thu 7 ngày gần nhất
    chart_days = []
    max_day_rev = 1
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        d_start = datetime(d.year, d.month, d.day, 0, 0, 0)
        d_end = datetime(d.year, d.month, d.day, 23, 59, 59)
        rev = db.session.scalar(
            db.select(func.sum(Order.total_amount)).where(
                Order.status == "Hoàn tất",
                Order.created_at >= d_start,
                Order.created_at <= d_end,
            )
        ) or 0
        if rev > max_day_rev:
            max_day_rev = rev
        chart_days.append({
            "label": d.strftime("%d/%m"),
            "revenue": rev,
            "is_today": (i == 0),
        })

    for item in chart_days:
        item["height_pct"] = max(12, int(round((item["revenue"] / max_day_rev) * 100))) if item["revenue"] > 0 else 8

    return render_template(
        "admin/dashboard.html",
        current_month=now.month,
        total_books=total_books,
        pending_orders=pending_orders,
        monthly_revenue=monthly_revenue,
        low_stock_count=low_stock_count,
        recent_orders=recent_orders,
        low_stock_books=low_stock_books,
        chart_days=chart_days,
    )


# --- Màn hình 7: Quản lý sách (/admin/books) ---
@app.get("/admin/books")
def admin_books():
    q = request.args.get("q", "").strip()
    cat_id_raw = request.args.get("category_id", "").strip()
    stock_filter = request.args.get("stock", "").strip()
    page_raw = request.args.get("page", "1").strip()

    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    selected_cat_id = None
    stmt = db.select(Book).order_by(Book.id.desc())

    if cat_id_raw:
        try:
            selected_cat_id = int(cat_id_raw)
            stmt = stmt.where(Book.category_id == selected_cat_id)
        except ValueError:
            selected_cat_id = None

    if q:
        stmt = stmt.where(
            (Book.title.ilike(f"%{q}%")) | (Book.author.ilike(f"%{q}%"))
        )

    if stock_filter == "available":
        stmt = stmt.where(Book.stock > 0)
    elif stock_filter == "low":
        stmt = stmt.where(Book.stock <= 5)
    elif stock_filter == "out":
        stmt = stmt.where(Book.stock == 0)

    all_matching_books = db.session.execute(stmt).scalars().all()
    total_filtered = len(all_matching_books)

    per_page = 5
    pages = max(1, math.ceil(total_filtered / per_page))
    if page > pages:
        page = pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    books_on_page = all_matching_books[start_idx:end_idx]

    # Kiểm tra sách nào đã có trong đơn hàng (không được xoá)
    ordered_book_ids = set(
        db.session.execute(db.select(OrderItem.book_id).distinct()).scalars().all()
    )

    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()

    return render_template(
        "admin/books.html",
        books=books_on_page,
        total_filtered=total_filtered,
        start_num=start_idx + 1 if total_filtered > 0 else 0,
        end_num=min(end_idx, total_filtered),
        page=page,
        pages=pages,
        q=q,
        selected_cat_id=selected_cat_id,
        stock_filter=stock_filter,
        categories=categories,
        ordered_book_ids=ordered_book_ids,
    )


# --- Màn hình 8: Thêm và sửa sách (/admin/books/new & /admin/books/<id>/edit) ---
def save_cover_image(file_storage, old_filename=None):
    """Lưu ảnh bìa tên ngẫu nhiên, xoá ảnh cũ nếu có."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return old_filename

    orig_name = secure_filename(file_storage.filename)
    ext = os.path.splitext(orig_name)[1].lower()
    new_filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)
    file_storage.save(save_path)

    if old_filename:
        old_path = os.path.join(app.config["UPLOAD_FOLDER"], old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    return new_filename


@app.route("/admin/books/new", methods=["GET", "POST"])
@app.route("/admin/books/<int:book_id>/edit", methods=["GET", "POST"])
def admin_book_form(book_id=None):
    book = None
    if book_id is not None:
        book = db.session.get(Book, book_id)
        if not book:
            abort(404, description="Không tìm thấy sách cần sửa.")

    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()
    form = BookForm(edit_book_id=book.id if book else None, obj=book)
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if request.method == "GET" and book:
        form.category_id.data = book.category_id

    if form.validate_on_submit():
        if book is None:
            cover_name = save_cover_image(form.cover_file.data, None)
            new_book = Book(
                title=form.title.data.strip(),
                author=form.author.data.strip(),
                category_id=form.category_id.data,
                publish_year=form.publish_year.data or datetime.now().year,
                publisher=(form.publisher.data or "NXB Đại học Huế").strip(),
                price=form.price.data,
                stock=form.stock.data,
                description=(form.description.data or "").strip(),
                cover_image=cover_name,
            )
            db.session.add(new_book)
            db.session.commit()
            flash(f'Đã thêm sách "{new_book.title}" thành công!', "success")
        else:
            book.title = form.title.data.strip()
            book.author = form.author.data.strip()
            book.category_id = form.category_id.data
            book.publish_year = form.publish_year.data or book.publish_year
            book.publisher = (form.publisher.data or book.publisher or "NXB Đại học Huế").strip()
            book.price = form.price.data
            book.stock = form.stock.data
            book.description = (form.description.data or "").strip()
            book.cover_image = save_cover_image(form.cover_file.data, book.cover_image)
            db.session.commit()
            flash(f'Đã cập nhật sách "{book.title}" thành công!', "success")

        return redirect(url_for("admin_books"))

    return render_template(
        "admin/book_form.html",
        form=form,
        book=book,
        is_edit=(book is not None),
    )


@app.post("/admin/books/<int:book_id>/delete")
def admin_book_delete(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        abort(404)

    # Kiểm tra sách đã có trong đơn hàng chưa
    in_orders = db.session.scalar(
        db.select(func.count(OrderItem.id)).where(OrderItem.book_id == book.id)
    ) or 0
    if in_orders > 0:
        flash(f'Không thể xoá sách "{book.title}" vì đã tồn tại trong {in_orders} chi tiết đơn hàng.', "danger")
        return redirect(url_for("admin_books"))

    if book.cover_image:
        old_path = os.path.join(app.config["UPLOAD_FOLDER"], book.cover_image)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    title = book.title
    db.session.delete(book)
    db.session.commit()
    flash(f'Đã xoá sách "{title}".', "info")
    return redirect(url_for("admin_books"))


# --- Màn hình 9: Danh mục sách (/admin/categories) ---
@app.route("/admin/categories", methods=["GET", "POST"])
def admin_categories():
    edit_id = request.args.get("edit_id", type=int)
    edit_cat = db.session.get(Category, edit_id) if edit_id else None

    form = CategoryForm(edit_cat_id=edit_cat.id if edit_cat else None, obj=edit_cat)

    if form.validate_on_submit():
        if edit_cat:
            edit_cat.name = form.name.data.strip()
            edit_cat.description = (form.description.data or "").strip()
            db.session.commit()
            flash(f'Đã cập nhật danh mục "{edit_cat.name}".', "success")
        else:
            new_cat = Category(
                name=form.name.data.strip(),
                description=(form.description.data or "").strip(),
            )
            db.session.add(new_cat)
            db.session.commit()
            flash(f'Đã thêm danh mục "{new_cat.name}".', "success")
        return redirect(url_for("admin_categories"))

    # Một truy vấn group_by lấy tất cả danh mục kèm số sách (kể cả danh mục 0 sách)
    stmt = (
        db.select(Category, func.count(Book.id).label("book_count"))
        .outerjoin(Book, Category.id == Book.category_id)
        .group_by(Category.id)
        .order_by(Category.id)
    )
    cat_rows = db.session.execute(stmt).all()

    return render_template(
        "admin/categories.html",
        cat_rows=cat_rows,
        form=form,
        edit_cat=edit_cat,
    )


@app.post("/admin/categories/<int:cat_id>/delete")
def admin_category_delete(cat_id):
    cat = db.session.get(Category, cat_id)
    if not cat:
        abort(404)

    book_count = db.session.scalar(
        db.select(func.count(Book.id)).where(Book.category_id == cat.id)
    ) or 0

    if book_count > 0:
        flash(f'✕ Không thể xoá "{cat.name}": còn {book_count} sách.', "danger")
        return redirect(url_for("admin_categories"))

    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    flash(f'Đã xoá danh mục "{name}".', "info")
    return redirect(url_for("admin_categories"))


# --- Màn hình 10: Danh sách đơn hàng (/admin/orders) ---
@app.get("/admin/orders")
def admin_orders():
    status_filter = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    page_raw = request.args.get("page", "1").strip()

    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    # Một truy vấn group_by đếm số đơn mỗi trạng thái
    counts_stmt = db.select(Order.status, func.count(Order.id)).group_by(Order.status)
    status_rows = db.session.execute(counts_stmt).all()
    status_counts = {
        "Chờ xác nhận": 0,
        "Đang giao": 0,
        "Hoàn tất": 0,
        "Đã huỷ": 0,
    }
    for st, cnt in status_rows:
        status_counts[st] = cnt
    total_all_orders = sum(status_counts.values())

    stmt = db.select(Order).order_by(Order.id.desc())
    if status_filter in status_counts:
        stmt = stmt.where(Order.status == status_filter)
    else:
        status_filter = ""

    if q:
        q_clean = q.lstrip("#").strip()
        if q_clean.isdigit():
            stmt = stmt.where(
                (Order.id == int(q_clean))
                | (Order.customer_name.ilike(f"%{q}%"))
                | (Order.customer_phone.ilike(f"%{q}%"))
            )
        else:
            stmt = stmt.where(
                (Order.customer_name.ilike(f"%{q}%"))
                | (Order.customer_phone.ilike(f"%{q}%"))
            )

    all_matching_orders = db.session.execute(stmt).scalars().all()
    filtered_count = len(all_matching_orders)
    filtered_total_value = sum(o.total_amount for o in all_matching_orders)

    per_page = 10
    pages = max(1, math.ceil(filtered_count / per_page))
    if page > pages:
        page = pages

    start_idx = (page - 1) * per_page
    orders_on_page = all_matching_orders[start_idx : start_idx + per_page]

    return render_template(
        "admin/orders.html",
        orders=orders_on_page,
        status_filter=status_filter,
        status_counts=status_counts,
        total_all_orders=total_all_orders,
        q=q,
        page=page,
        pages=pages,
        filtered_count=filtered_count,
        filtered_total_value=filtered_total_value,
    )


# --- Màn hình 11: Chi tiết đơn hàng (/admin/orders/<int:order_id>) ---
VALID_NEXT_STATUS = {
    "Chờ xác nhận": ["Đang giao"],
    "Đang giao": ["Hoàn tất"],
    "Hoàn tất": [],
    "Đã huỷ": [],
}


@app.get("/admin/orders/<int:order_id>")
def admin_order_detail(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404, description="Không tìm thấy đơn hàng.")

    next_options = VALID_NEXT_STATUS.get(order.status, [])
    can_cancel = order.status in ("Chờ xác nhận", "Đang giao")

    return render_template(
        "admin/order_detail.html",
        order=order,
        next_options=next_options,
        can_cancel=can_cancel,
    )


@app.post("/admin/orders/<int:order_id>/status")
def admin_order_update_status(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    action = request.form.get("action", "update")
    now = datetime.now()

    if action == "cancel":
        if order.status not in ("Chờ xác nhận", "Đang giao"):
            flash("Đơn hàng ở trạng thái này không thể huỷ.", "danger")
            return redirect(url_for("admin_order_detail", order_id=order.id))

        # Hoàn lại tồn kho các sách trong đơn
        for item in order.items:
            if item.book:
                item.book.stock += item.quantity

        order.status = "Đã huỷ"
        db.session.add(OrderLog(
            order_id=order.id,
            status="Đã huỷ",
            label="Đã huỷ (đã hoàn tồn kho)",
            changed_at=now,
        ))
        db.session.commit()
        flash(f"Đã huỷ đơn hàng #{order.id} và hoàn lại tồn kho các sách.", "info")
        return redirect(url_for("admin_order_detail", order_id=order.id))

    new_status = request.form.get("new_status", "").strip()
    allowed = VALID_NEXT_STATUS.get(order.status, [])
    if new_status not in allowed:
        flash(f'Không thể chuyển trạng thái từ "{order.status}" sang "{new_status}".', "danger")
        return redirect(url_for("admin_order_detail", order_id=order.id))

    order.status = new_status
    db.session.add(OrderLog(
        order_id=order.id,
        status=new_status,
        label=new_status,
        changed_at=now,
    ))
    db.session.commit()
    flash(f'Đã cập nhật trạng thái đơn #{order.id} sang "{new_status}".', "success")
    return redirect(url_for("admin_order_detail", order_id=order.id))


# --- XỬ LÝ LỖI 404 ---
@app.errorhandler(404)
def handle_404(error):
    return render_template("404.html", error=error), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
