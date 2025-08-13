#!/usr/bin/env python3
"""
HotelJT – Gestão de Hotel (22 quartos) em um único arquivo
Stack: Python 3.10+, Flask, SQLAlchemy, SQLite.

Funcionalidades principais:
- Dashboard com ocupação do dia e receita do mês
- Cadastro de hóspedes
- Reservas (criar/editar/cancelar)
- Check-in / Check-out com cálculo automático de diárias
- Mapa de quartos (22 unidades) com status em tempo real
- Relatórios simples (ocupação por período, receita por período)
- Seed inicial com 22 quartos

Como rodar (Ubuntu):
  python3 -m venv .venv && source .venv/bin/activate
  pip install Flask SQLAlchemy python-dateutil
  export FLASK_APP=app.py FLASK_ENV=development
  python app.py  # primeira execução cria o banco e os 22 quartos
  # depois acesse http://127.0.0.1:5000

Banco: hotelJT.db (SQLite) criado no diretório atual.
"""

from __future__ import annotations
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil import tz
from flask import Flask, redirect, render_template_string, request, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, and_, or_, UniqueConstraint

APP_TZ = tz.gettz(os.getenv("TZ", "America/Sao_Paulo"))

def today() -> date:
    return datetime.now(tz=APP_TZ).date()

app = Flask(__name__)
app.config.update(
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///hotelJT.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-key-change-me"),
)

db = SQLAlchemy(app)

# --------------------------
# Models
# --------------------------
class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(8), unique=True, nullable=False)
    room_type = db.Column(db.String(20), default="Standard", nullable=False)
    rate = db.Column(db.Numeric(10, 2), default=Decimal("220.00"), nullable=False)
    # derived status: livre, reservado, ocupado, manutenção – calculado na view

    def __repr__(self):
        return f"<Room {self.number}>"

class Guest(db.Model):
    __tablename__ = "guests"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    document = db.Column(db.String(40), nullable=True)  # CPF/RG/Passaporte
    phone = db.Column(db.String(40), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    __table_args__ = (UniqueConstraint('document', name='uq_guest_document'),)

    def __repr__(self):
        return f"<Guest {self.name}>"

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    guest_id = db.Column(db.Integer, db.ForeignKey("guests.id"), nullable=False)
    check_in = db.Column(db.Date, nullable=False)
    check_out = db.Column(db.Date, nullable=False)  # data de saída prevista
    status = db.Column(db.String(20), default="reservado", nullable=False)  # reservado|checkin|checkout|cancelado
    notes = db.Column(db.Text, nullable=True)
    total_amount = db.Column(db.Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz=APP_TZ))

    room = db.relationship(Room)
    guest = db.relationship(Guest)

    def nights(self) -> int:
        # Garante que mesmo check-in e check-out no mesmo dia conte como 1 noite
        return max((self.check_out - self.check_in).days, 1)

    def compute_amount(self) -> Decimal:
        return (self.room.rate or Decimal("0.00")) * self.nights()

# --------------------------
# DB bootstrap
# --------------------------
with app.app_context():
    db.create_all()
    # Seed 22 rooms with correct types and rates
    if Room.query.count() == 0:
        rooms = []
        for n in range(101, 106): rooms.append(Room(number=str(n), room_type="Single", rate=Decimal("110.00")))
        for n in range(106, 116): rooms.append(Room(number=str(n), room_type="Duplo", rate=Decimal("200.00")))
        for n in range(116, 121): rooms.append(Room(number=str(n), room_type="Triplo", rate=Decimal("290.00")))
        for n in range(121, 123): rooms.append(Room(number=str(n), room_type="Quadruplo", rate=Decimal("360.00")))
        db.session.add_all(rooms)
        db.session.commit()

# --------------------------
# Helpers
# --------------------------
STATUS_BADGE = {
    "livre": "bg-green-100 text-green-800",
    "reservado": "bg-yellow-100 text-yellow-800",
    "checkin": "bg-blue-100 text-blue-800",
    "checkout": "bg-gray-100 text-gray-800",
    "cancelado": "bg-red-100 text-red-800",
}

def room_status(room: Room, reference: date | None = None) -> str:
    reference = reference or today()
    active = Booking.query.filter(
        Booking.room_id == room.id,
        Booking.status.in_(["reservado", "checkin"]),
        Booking.check_in <= reference,
        Booking.check_out > reference,
    ).order_by(Booking.check_in.desc()).first()
    if active:
        return "checkin" if active.status == "checkin" else "reservado"
    return "livre"

# --------------------------
# Templates (Tailwind via CDN)
# --------------------------
BASE_HTML = """
<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>HotelJT</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-slate-50 text-slate-900">
    <nav class="bg-slate-900 text-white px-4 py-3 flex gap-4 items-center">
      <a href="{{ url_for('dashboard') }}" class="font-bold">HotelJT</a>
      <a href="{{ url_for('rooms') }}" class="hover:underline">Quartos</a>
      <a href="{{ url_for('guests') }}" class="hover:underline">Hóspedes</a>
      <a href="{{ url_for('bookings') }}" class="hover:underline">Reservas</a>
      <a href="{{ url_for('reports') }}" class="hover:underline">Relatórios</a>
      <span class="ml-auto text-sm opacity-80">{{ now.strftime('%d/%m/%Y') }}</span>
    </nav>
    <main class="p-4 max-w-6xl mx-auto">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="mb-4">{% for m in messages %}
            <div class="p-3 rounded bg-emerald-100 text-emerald-900 mb-2">{{ m }}</div>
          {% endfor %}</div>
        {% endif %}
      {% endwith %}
      {{ content|safe }}
    </main>
  </body>
</html>
"""

# --------------------------
# Views
# --------------------------
@app.context_processor
def inject_now():
    return {"now": datetime.now(tz=APP_TZ)}

@app.route("/")
def dashboard():
    d = today()
    occupied = (
        db.session.query(func.count(Booking.id))
        .filter(Booking.status.in_(["checkin"]), Booking.check_in <= d, Booking.check_out > d)
        .scalar()
    )
    total_rooms = Room.query.count()

    start_month = d.replace(day=1)
    next_month = (start_month + timedelta(days=32)).replace(day=1)
    revenue = (
        db.session.query(func.coalesce(func.sum(Booking.total_amount), 0))
        .filter(Booking.status == "checkout", Booking.check_out >= start_month, Booking.check_out < next_month)
        .scalar()
    )

    upcoming = (
        Booking.query.filter(Booking.status == "reservado", Booking.check_in >= d)
        .order_by(Booking.check_in.asc())
        .limit(5)
        .all()
    )

    content = render_template_string(
        """
        <div class="grid md:grid-cols-3 gap-4">
          <div class="p-4 rounded-2xl bg-white shadow">
            <div class="text-sm opacity-70">Ocupação hoje</div>
            <div class="text-3xl font-bold">{{ occupied }}/{{ total_rooms }}</div>
          </div>
          <div class="p-4 rounded-2xl bg-white shadow">
            <div class="text-sm opacity-70">Receita do mês</div>
            <div class="text-3xl font-bold">R$ {{ '%.2f'|format(revenue) }}</div>
          </div>
        </div>

        <h2 class="mt-8 mb-2 font-semibold text-lg">Próximos check-ins</h2>
        <div class="bg-white shadow rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-slate-100">
              <tr><th class="p-2 text-left">Data</th><th class="p-2 text-left">Quarto</th><th class="p-2 text-left">Hóspede</th><th></th></tr>
            </thead>
            <tbody>
              {% for b in upcoming %}
              <tr class="border-t">
                <td class="p-2">{{ b.check_in.strftime('%d/%m/%Y') }}</td>
                <td class="p-2">{{ b.room.number }}</td>
                <td class="p-2">{{ b.guest.name }}</td>
                <td class="p-2"><a class="underline" href="{{ url_for('booking_detail', booking_id=b.id) }}">Abrir</a></td>
              </tr>
              {% else %}
              <tr><td class="p-2" colspan="4">Sem reservas futuras.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        """,
        occupied=occupied,
        total_rooms=total_rooms,
        revenue=float(revenue or 0),
        upcoming=upcoming
    )
    return render_template_string(BASE_HTML, content=content)

@app.route("/quartos")
def rooms():
    all_rooms = Room.query.order_by(Room.number.asc()).all()
    items = [(r, room_status(r)) for r in all_rooms]
    content = render_template_string(
        """
        <div class="flex items-center mb-4">
          <h1 class="text-xl font-semibold">Quartos</h1>
          <a href="{{ url_for('new_booking') }}" class="ml-auto inline-block px-3 py-2 bg-slate-900 text-white rounded-xl shadow">Nova reserva</a>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          {% for room, st in items %}
            <a href="{{ url_for('room_detail', room_id=room.id) }}" class="p-3 rounded-2xl shadow bg-white">
              <div class="text-sm opacity-60">Quarto</div>
              <div class="text-2xl font-bold">{{ room.number }}</div>
              <div class="mt-2 text-xs inline-block px-2 py-1 rounded {{ STATUS_BADGE[st] }}">{{ st }}</div>
              <div class="text-xs opacity-70 mt-1">R$ {{ '%.2f'|format(room.rate) }}/noite</div>
              <div class="text-xs opacity-70">{{ room.room_type }}</div>
            </a>
          {% endfor %}
        </div>
        """,
        items=items,
        STATUS_BADGE=STATUS_BADGE,
    )
    return render_template_string(BASE_HTML, content=content)

@app.route("/quartos/<int:room_id>")
def room_detail(room_id: int):
    room = Room.query.get_or_404(room_id)
    recent = (
        Booking.query.filter(Booking.room_id == room.id)
        .order_by(Booking.check_in.desc())
        .limit(10)
        .all()
    )
    st = room_status(room)
    content = render_template_string(
        """
        <div class="flex items-center mb-4">
          <h1 class="text-xl font-semibold">Quarto {{ room.number }}</h1>
          <a href="{{ url_for('new_booking', room_id=room.id) }}" class="ml-auto inline-block px-3 py-2 bg-slate-900 text-white rounded-xl shadow">Reservar</a>
        </div>
        <div class="bg-white rounded-2xl shadow p-4">
          <div class="flex gap-6">
            <div><div class="text-sm opacity-60">Tipo</div><div class="font-semibold">{{ room.room_type }}</div></div>
            <div><div class="text-sm opacity-60">Diária</div><div class="font-semibold">R$ {{ '%.2f'|format(room.rate) }}</div></div>
            <div><div class="text-sm opacity-60">Status</div><div class="text-xs inline-block px-2 py-1 rounded {{ STATUS_BADGE[st] }}">{{ st }}</div></div>
          </div>
        </div>
        <h2 class="mt-6 mb-2 font-semibold">Últimas reservas</h2>
        <div class="bg-white shadow rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-slate-100"><tr><th class="p-2 text-left">Período</th><th class="p-2 text-left">Hóspede</th><th class="p-2 text-left">Status</th><th></th></tr></thead>
            <tbody>
            {% for b in recent %}
              <tr class="border-t">
                <td class="p-2">{{ b.check_in.strftime('%d/%m/%Y') }} → {{ b.check_out.strftime('%d/%m/%Y') }}</td>
                <td class="p-2">{{ b.guest.name }}</td>
                <td class="p-2">{{ b.status }}</td>
                <td class="p-2"><a class="underline" href="{{ url_for('booking_detail', booking_id=b.id) }}">Abrir</a></td>
              </tr>
            {% else %}
              <tr><td class="p-2" colspan="4">Sem histórico.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        """,
        room=room, STATUS_BADGE=STATUS_BADGE, st=st, recent=recent
    )
    return render_template_string(BASE_HTML, content=content)

# -------------------------- Hóspedes --------------------------
@app.route("/hospedes")
def guests():
    q = request.args.get("q", "")
    base = Guest.query
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Guest.name.ilike(like), Guest.document.ilike(like)))
    gs = base.order_by(Guest.name.asc()).limit(200).all()

    content = render_template_string(
        """
        <div class="flex items-center mb-4">
          <h1 class="text-xl font-semibold">Hóspedes</h1>
          <form class="ml-4" method="get"><input name="q" value="{{ request.args.get('q','') }}" placeholder="Buscar" class="px-3 py-2 border rounded-xl"></form>
          <a href="{{ url_for('new_guest') }}" class="ml-auto inline-block px-3 py-2 bg-slate-900 text-white rounded-xl shadow">Novo hóspede</a>
        </div>
        <div class="bg-white shadow rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-slate-100"><tr><th class="p-2 text-left">Nome</th><th class="p-2 text-left">Documento</th><th class="p-2 text-left">Contato</th><th></th></tr></thead>
            <tbody>
              {% for g in gs %}
              <tr class="border-t">
                <td class="p-2">{{ g.name }}</td>
                <td class="p-2">{{ g.document or '-' }}</td>
                <td class="p-2">{{ g.phone or '-' }} {{ g.email or '' }}</td>
                <td class="p-2"><a class="underline" href="{{ url_for('edit_guest', guest_id=g.id) }}">Editar</a></td>
              </tr>
              {% else %}
              <tr><td class="p-2" colspan="4">Sem registros.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        """,
        gs=gs,
    )
    return render_template_string(BASE_HTML, content=content)

@app.route("/hospedes/novo", methods=["GET", "POST"])
def new_guest():
    if request.method == "POST":
        g = Guest(
            name=request.form["name"].strip(),
            document=request.form.get("document", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
        )
        db.session.add(g)
        db.session.commit()
        flash("Hóspede cadastrado.")
        # CORREÇÃO: Redireciona para a página do hóspede recém-criado ou para a lista de hóspedes
        return redirect(url_for("guests"))
    content = render_template_string(
        """
        <h1 class="text-xl font-semibold mb-4">Novo hóspede</h1>
        <form method="post" class="bg-white p-4 rounded-2xl shadow grid gap-3 md:w-2/3">
          <input name="name" required placeholder="Nome completo" class="px-3 py-2 border rounded-xl">
          <input name="document" placeholder="Documento (CPF/RG/Passaporte)" class="px-3 py-2 border rounded-xl">
          <input name="phone" placeholder="Telefone" class="px-3 py-2 border rounded-xl">
          <input name="email" placeholder="E-mail" class="px-3 py-2 border rounded-xl">
          <button class="px-3 py-2 bg-slate-900 text-white rounded-xl">Salvar</button>
        </form>
        """
    )
    return render_template_string(BASE_HTML, content=content)

@app.route("/hospedes/<int:guest_id>/editar", methods=["GET", "POST"])
def edit_guest(guest_id: int):
    g = Guest.query.get_or_404(guest_id)
    if request.method == "POST":
        g.name = request.form["name"].strip()
        g.document = request.form.get("document", "").strip() or None
        g.phone = request.form.get("phone", "").strip() or None
        g.email = request.form.get("email", "").strip() or None
        db.session.commit()
        flash("Hóspede atualizado.")
        return redirect(url_for("guests"))
    content = render_template_string(
        """
        <h1 class="text-xl font-semibold mb-4">Editar hóspede</h1>
        <form method="post" class="bg-white p-4 rounded-2xl shadow grid gap-3 md:w-2/3">
          <input name="name" value="{{ g.name }}" required class="px-3 py-2 border rounded-xl">
          <input name="document" value="{{ g.document or '' }}" class="px-3 py-2 border rounded-xl">
          <input name="phone" value="{{ g.phone or '' }}" class="px-3 py-2 border rounded-xl">
          <input name="email" value="{{ g.email or '' }}" class="px-3 py-2 border rounded-xl">
          <button class="px-3 py-2 bg-slate-900 text-white rounded-xl">Salvar</button>
        </form>
        """,
        g=g,
    )
    return render_template_string(BASE_HTML, content=content)

# -------------------------- Reservas --------------------------
@app.route("/reservas")
def bookings():
    status = request.args.get("status", "")
    base = Booking.query
    if status:
        base = base.filter(Booking.status == status)
    bs = base.order_by(Booking.check_in.desc()).limit(200).all()

    content = render_template_string(
        """
        <div class="flex items-center mb-4">
          <h1 class="text-xl font-semibold">Reservas</h1>
          <a href="{{ url_for('new_booking') }}" class="ml-auto inline-block px-3 py-2 bg-slate-900 text-white rounded-xl shadow">Nova reserva</a>
        </div>
        <div class="bg-white shadow rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-slate-100"><tr><th class="p-2 text-left">Período</th><th class="p-2 text-left">Quarto</th><th class="p-2 text-left">Hóspede</th><th class="p-2 text-left">Status</th><th class="p-2 text-right">Total</th><th></th></tr></thead>
            <tbody>
              {% for b in bs %}
              <tr class="border-t">
                <td class="p-2">{{ b.check_in.strftime('%d/%m/%Y') }} → {{ b.check_out.strftime('%d/%m/%Y') }}</td>
                <td class="p-2">{{ b.room.number }}</td>
                <td class="p-2">{{ b.guest.name }}</td>
                <td class="p-2">{{ b.status }}</td>
                <td class="p-2 text-right">R$ {{ '%.2f'|format(b.total_amount) }}</td>
                <td class="p-2"><a class="underline" href="{{ url_for('booking_detail', booking_id=b.id) }}">Abrir</a></td>
              </tr>
              {% else %}
              <tr><td class="p-2" colspan="6">Sem reservas.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        """,
        bs=bs,
    )
    return render_template_string(BASE_HTML, content=content)

# CORREÇÃO: Esta é a função para criar uma NOVA reserva. A rota duplicada foi removida.
@app.route("/reservas/nova", methods=["GET", "POST"])
@app.route("/reservas/nova/quarto/<int:room_id>", methods=["GET", "POST"])
def new_booking(room_id: int | None = None):
    if request.method == "POST":
        room_id_form = int(request.form["room_id"])
        guest_id = int(request.form["guest_id"])
        check_in = datetime.strptime(request.form["check_in"], "%Y-%m-%d").date()
        check_out = datetime.strptime(request.form["check_out"], "%Y-%m-%d").date()
        notes = request.form.get("notes")

        if check_out <= check_in:
            flash("Data de check-out deve ser após check-in")
            return redirect(request.url)

        conflict = Booking.query.filter(
            Booking.room_id == room_id_form,
            Booking.status.in_(["reservado", "checkin"]),
            Booking.check_in < check_out,
            Booking.check_out > check_in,
        ).first()
        if conflict:
            flash(f"Conflito: quarto já reservado/ocupado por {conflict.guest.name} nesse período.")
            return redirect(url_for("new_booking", room_id=room_id_form))

        b = Booking(
            room_id=room_id_form, guest_id=guest_id, check_in=check_in, check_out=check_out,
            status="reservado", notes=notes
        )
        b.total_amount = b.compute_amount()
        db.session.add(b)
        db.session.commit()
        flash("Reserva criada.")
        return redirect(url_for("booking_detail", booking_id=b.id))

    rooms = Room.query.order_by(Room.number.asc()).all()
    guests = Guest.query.order_by(Guest.name.asc()).all()
    content = render_template_string(
        """
        <h1 class="text-xl font-semibold mb-4">Nova reserva</h1>
        <form method="post" class="bg-white p-4 rounded-2xl shadow grid gap-3 md:w-2/3">
          <label class="text-sm">Quarto
            <select name="room_id" class="px-3 py-2 border rounded-xl w-full">
              {% for r in rooms %}
                <option value="{{ r.id }}" {% if pre_room_id==r.id %}selected{% endif %}>{{ r.number }} ({{ r.room_type }}) – R$ {{ '%.2f'|format(r.rate) }}</option>
              {% endfor %}
            </select>
          </label>
          <label class="text-sm">Hóspede
            <select name="guest_id" class="px-3 py-2 border rounded-xl w-full">
              {% for g in guests %}
                <option value="{{ g.id }}">{{ g.name }}{% if g.document %} ({{ g.document }}){% endif %}</option>
              {% endfor %}
            </select>
          </label>
          <div class="grid md:grid-cols-2 gap-3">
            <label class="text-sm">Check-in <input type="date" name="check_in" value="{{ now.strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
            <label class="text-sm">Check-out <input type="date" name="check_out" value="{{ (now + timedelta(days=1)).strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
          </div>
          <textarea name="notes" placeholder="Observações" class="px-3 py-2 border rounded-xl"></textarea>
          <button class="px-3 py-2 bg-slate-900 text-white rounded-xl">Criar reserva</button>
        </form>
        <p class="text-sm mt-3">Precisa cadastrar o hóspede? <a class="underline" href="{{ url_for('new_guest') }}">Clique aqui</a>.</p>
        """,
        rooms=rooms, guests=guests, pre_room_id=room_id, timedelta=timedelta
    )
    return render_template_string(BASE_HTML, content=content)


# CORREÇÃO: Esta é a nova função para EDITAR uma reserva existente.
@app.route("/reservas/<int:booking_id>/editar", methods=["GET", "POST"])
def booking_edit(booking_id: int):
    b = Booking.query.get_or_404(booking_id)
    if request.method == "POST":
        room_id = int(request.form["room_id"])
        guest_id = int(request.form["guest_id"])
        check_in = datetime.strptime(request.form["check_in"], "%Y-%m-%d").date()
        check_out = datetime.strptime(request.form["check_out"], "%Y-%m-%d").date()
        notes = request.form.get("notes")

        if check_out <= check_in:
            flash("Data de check-out deve ser após check-in.")
            return redirect(request.url)

        # Verifica conflito com OUTRAS reservas
        conflict = Booking.query.filter(
            Booking.id != booking_id, # Ignora a própria reserva
            Booking.room_id == room_id,
            Booking.status.in_(["reservado", "checkin"]),
            Booking.check_in < check_out,
            Booking.check_out > check_in,
        ).first()
        if conflict:
            flash(f"Conflito: quarto já reservado/ocupado por {conflict.guest.name} nesse período.")
            return redirect(request.url)

        b.room_id = room_id
        b.guest_id = guest_id
        b.check_in = check_in
        b.check_out = check_out
        b.notes = notes
        b.total_amount = b.compute_amount()
        db.session.commit()
        flash("Reserva atualizada.")
        return redirect(url_for("booking_detail", booking_id=b.id))

    rooms = Room.query.order_by(Room.number.asc()).all()
    guests = Guest.query.order_by(Guest.name.asc()).all()
    content = render_template_string(
        """
        <h1 class="text-xl font-semibold mb-4">Editar reserva #{{ b.id }}</h1>
        <form method="post" class="bg-white p-4 rounded-2xl shadow grid gap-3 md:w-2/3">
          <label class="text-sm">Quarto
            <select name="room_id" class="px-3 py-2 border rounded-xl w-full">
              {% for r in rooms %}
                <option value="{{ r.id }}" {% if b.room_id==r.id %}selected{% endif %}>{{ r.number }} ({{ r.room_type }}) – R$ {{ '%.2f'|format(r.rate) }}</option>
              {% endfor %}
            </select>
          </label>
          <label class="text-sm">Hóspede
            <select name="guest_id" class="px-3 py-2 border rounded-xl w-full">
              {% for g in guests %}
                <option value="{{ g.id }}" {% if b.guest_id==g.id %}selected{% endif %}>{{ g.name }}</option>
              {% endfor %}
            </select>
          </label>
          <div class="grid md:grid-cols-2 gap-3">
            <label class="text-sm">Check-in <input type="date" name="check_in" value="{{ b.check_in.strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
            <label class="text-sm">Check-out <input type="date" name="check_out" value="{{ b.check_out.strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
          </div>
          <textarea name="notes" class="px-3 py-2 border rounded-xl">{{ b.notes or '' }}</textarea>
          <button class="px-3 py-2 bg-slate-900 text-white rounded-xl">Salvar</button>
        </form>
        """,
        b=b, rooms=rooms, guests=guests
    )
    return render_template_string(BASE_HTML, content=content)


@app.route("/reservas/<int:booking_id>")
def booking_detail(booking_id: int):
    b = Booking.query.get_or_404(booking_id)
    content = render_template_string(
        """
        <div class="flex items-center mb-4">
          <h1 class="text-xl font-semibold">Reserva #{{ b.id }} – Quarto {{ b.room.number }}</h1>
          <a href="{{ url_for('bookings') }}" class="ml-auto underline">Voltar</a>
        </div>
        <div class="bg-white rounded-2xl shadow p-4 grid gap-3">
          <div class="grid md:grid-cols-4 gap-3">
            <div><div class="text-sm opacity-60">Hóspede</div><div class="font-semibold">{{ b.guest.name }}</div></div>
            <div><div class="text-sm opacity-60">Período</div><div class="font-semibold">{{ b.check_in.strftime('%d/%m/%Y') }} → {{ b.check_out.strftime('%d/%m/%Y') }} ({{ b.nights() }} noites)</div></div>
            <div><div class="text-sm opacity-60">Status</div><div class="font-semibold">{{ b.status }}</div></div>
            <div><div class="text-sm opacity-60">Total</div><div class="font-semibold">R$ {{ '%.2f'|format(b.total_amount) }}</div></div>
          </div>
          <div class="flex gap-2">
            {% if b.status == 'reservado' %}
              <a href="{{ url_for('booking_checkin', booking_id=b.id) }}" class="px-3 py-2 bg-blue-600 text-white rounded-xl">Fazer check-in</a>
              <a href="{{ url_for('booking_cancel', booking_id=b.id) }}" class="px-3 py-2 bg-red-600 text-white rounded-xl">Cancelar</a>
            {% elif b.status == 'checkin' %}
              <a href="{{ url_for('booking_checkout', booking_id=b.id) }}" class="px-3 py-2 bg-emerald-600 text-white rounded-xl">Fazer check-out</a>
            {% endif %}
            <a href="{{ url_for('booking_edit', booking_id=b.id) }}" class="px-3 py-2 bg-slate-900 text-white rounded-xl">Editar</a>
          </div>
          {% if b.notes %}<div class="pt-2 border-t mt-2"><div class="text-sm opacity-60">Observações</div><div>{{ b.notes }}</div></div>{% endif %}
        </div>
        """,
        b=b,
    )
    return render_template_string(BASE_HTML, content=content)

@app.route("/reservas/<int:booking_id>/checkin")
def booking_checkin(booking_id: int):
    b = Booking.query.get_or_404(booking_id)
    if b.status != "reservado":
        flash("Operação inválida. Apenas reservas com status 'reservado' podem fazer check-in.")
        return redirect(url_for("booking_detail", booking_id=b.id))
    b.status = "checkin"
    db.session.commit()
    flash("Check-in realizado.")
    return redirect(url_for("booking_detail", booking_id=b.id))

@app.route("/reservas/<int:booking_id>/checkout")
def booking_checkout(booking_id: int):
    b = Booking.query.get_or_404(booking_id)
    if b.status != "checkin":
        flash("Operação inválida. Apenas hóspedes com status 'checkin' podem fazer check-out.")
        return redirect(url_for("booking_detail", booking_id=b.id))
    b.check_out = today() # Opcional: ajustar a data de checkout para o dia atual
    b.total_amount = b.compute_amount()
    b.status = "checkout"
    db.session.commit()
    flash("Check-out realizado.")
    return redirect(url_for("booking_detail", booking_id=b.id))

@app.route("/reservas/<int:booking_id>/cancelar")
def booking_cancel(booking_id: int):
    b = Booking.query.get_or_404(booking_id)
    if b.status in ("checkout", "cancelado"):
        flash("Operação inválida. Esta reserva já foi finalizada ou cancelada.")
        return redirect(url_for("booking_detail", booking_id=b.id))
    b.status = "cancelado"
    db.session.commit()
    flash("Reserva cancelada.")
    return redirect(url_for("booking_detail", booking_id=b.id))

# -------------------------- Relatórios --------------------------
# CORREÇÃO: Função de relatórios completada e com lógica de cálculo de ocupação corrigida.
@app.route("/relatorios", methods=["GET", "POST"])
def reports():
    start_str = request.form.get("d1") if request.method == "POST" else request.args.get("d1")
    end_str = request.form.get("d2") if request.method == "POST" else request.args.get("d2")

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            if end_date <= start_date:
                flash("Data final deve ser maior que data inicial")
                start_date, end_date = None, None # Reset
        except ValueError:
            flash("Datas inválidas")
            start_date, end_date = None, None # Reset
    else:
        # Padrão: mês atual
        t = today()
        start_date = t.replace(day=1)
        end_date = (start_date + timedelta(days=32)).replace(day=1)

    total_revenue = Decimal("0.00")
    occupation_rate = 0.0
    
    if start_date and end_date:
        # Receita no período (baseado na data de check-out)
        total_revenue = db.session.query(func.coalesce(func.sum(Booking.total_amount), 0)).filter(
            Booking.status == "checkout", Booking.check_out >= start_date, Booking.check_out < end_date
        ).scalar() or Decimal("0.00")

        # Taxa de ocupação: (noites ocupadas no período) / (quartos * dias no período)
        period_days = (end_date - start_date).days
        total_rooms = Room.query.count()
        total_room_nights_available = period_days * total_rooms
        
        occupied_nights = 0
        if total_room_nights_available > 0:
            # Encontra todas as reservas que se sobrepõem ao período
            overlapping_bookings = Booking.query.filter(
                Booking.status.in_(["checkin", "checkout"]),
                Booking.check_in < end_date,
                Booking.check_out > start_date,
            ).all()

            for b in overlapping_bookings:
                # Calcula a interseção da reserva com o período do relatório
                overlap_start = max(b.check_in, start_date)
                overlap_end = min(b.check_out, end_date)
                occupied_nights += (overlap_end - overlap_start).days
            
            occupation_rate = (occupied_nights / total_room_nights_available) * 100 if total_room_nights_available > 0 else 0

    content = render_template_string(
        """
        <h1 class="text-xl font-semibold mb-4">Relatórios</h1>
        <form method="post" class="bg-white p-4 rounded-2xl shadow grid md:grid-cols-3 gap-3 items-end">
            <label class="text-sm">Data inicial <input type="date" name="d1" value="{{ start.strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
            <label class="text-sm">Data final <input type="date" name="d2" value="{{ end.strftime('%Y-%m-%d') }}" class="px-3 py-2 border rounded-xl w-full"></label>
            <button class="px-3 py-2 bg-slate-900 text-white rounded-xl h-fit">Gerar</button>
        </form>
        <div class="mt-6 grid md:grid-cols-2 gap-4">
            <div class="p-4 rounded-2xl bg-white shadow">
                <div class="text-sm opacity-70">Receita no período</div>
                <div class="text-3xl font-bold">R$ {{ '%.2f'|format(revenue) }}</div>
            </div>
            <div class="p-4 rounded-2xl bg-white shadow">
                <div class="text-sm opacity-70">Taxa de ocupação média</div>
                <div class="text-3xl font-bold">{{ '%.2f'|format(rate) }}%</div>
            </div>
        </div>
        """,
        start=start_date, end=end_date, revenue=float(total_revenue), rate=occupation_rate
    )
    return render_template_string(BASE_HTML, content=content)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")