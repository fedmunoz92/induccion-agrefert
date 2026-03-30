"""
SGC Agrefert — Sistema de Gestión de Calidad ISO 9001:2015
Aplicación principal Flask
"""
import os, json
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   jsonify, abort, session)
from flask_login import (LoginManager, login_user, logout_user, login_required,
                         current_user)
from flask_mail import Mail, Message
from models import (db, User, Area, DocumentType, Document, DocumentVersion,
                    FormTemplate, FormSubmission, QualityObjective,
                    ObjectiveMeasurement, NonConformity, Audit, CustomerClaim,
                    Notification, ManagementReview)

# ── App Configuration ─────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'agrefert-sgc-2026-secret-key')
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'sgc_agrefert.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email config (configurar con datos reales)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'sgc@agrefert.com')

db.init_app(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Iniciá sesión para acceder al SGC.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── Helpers ────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('admin', 'responsable'):
            abort(403)
        return f(*args, **kwargs)
    return decorated

def send_notification(user_id, title, message, notif_type='info', severity='info', entity_type=None, entity_id=None):
    """Crea notificación en BD y opcionalmente envía email"""
    notif = Notification(user_id=user_id, title=title, message=message,
                         notif_type=notif_type, severity=severity,
                         entity_type=entity_type, entity_id=entity_id)
    db.session.add(notif)
    db.session.commit()
    # Intentar enviar email
    try:
        user = User.query.get(user_id)
        if user and user.email and app.config['MAIL_USERNAME']:
            severity_emoji = {'info': 'ℹ️', 'warning': '⚠️', 'danger': '🔴'}.get(severity, '')
            msg = Message(
                subject=f"{severity_emoji} SGC Agrefert — {title}",
                recipients=[user.email],
                html=f"""
                <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
                    <div style="background:#1a472a;color:white;padding:20px;text-align:center;">
                        <h2 style="margin:0;">SGC Agrefert</h2>
                        <p style="margin:5px 0 0;opacity:0.8;">Sistema de Gestión de Calidad ISO 9001:2015</p>
                    </div>
                    <div style="padding:25px;background:#fff;border:1px solid #e0e0e0;">
                        <h3 style="color:#1a472a;">{title}</h3>
                        <p>{message}</p>
                        <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
                        <p style="color:#888;font-size:12px;">Este es un mensaje automático del SGC de Agrefert.</p>
                    </div>
                </div>
                """
            )
            mail.send(msg)
            notif.email_sent = True
            db.session.commit()
    except Exception as e:
        print(f"Error enviando email: {e}")

def check_deadlines():
    """Revisa vencimientos y genera alertas"""
    today = date.today()
    # Documentos próximos a vencer
    docs = Document.query.filter(Document.next_review_date != None, Document.status == 'vigente').all()
    for doc in docs:
        days_left = (doc.next_review_date - today).days
        if days_left == 30:
            send_notification(doc.created_by or 1, f"Revisión próxima: {doc.code}",
                f"El documento {doc.code} — {doc.title} vence en 30 días ({doc.next_review_date}).",
                'vencimiento', 'warning', 'document', doc.id)
        elif days_left == 7:
            send_notification(doc.created_by or 1, f"Revisión urgente: {doc.code}",
                f"El documento {doc.code} — {doc.title} vence en 7 días ({doc.next_review_date}).",
                'vencimiento', 'danger', 'document', doc.id)
        elif days_left < 0:
            send_notification(doc.created_by or 1, f"VENCIDO: {doc.code}",
                f"El documento {doc.code} — {doc.title} está vencido desde {doc.next_review_date}.",
                'vencimiento', 'danger', 'document', doc.id)
    # No conformidades vencidas
    ncs = NonConformity.query.filter(NonConformity.due_date != None,
                                      NonConformity.status.in_(['abierta', 'en_tratamiento'])).all()
    for nc in ncs:
        days_left = (nc.due_date - today).days
        if days_left <= 0:
            send_notification(nc.assigned_to or nc.raised_by or 1,
                f"NC vencida: {nc.code}", f"La no conformidad {nc.code} venció el {nc.due_date}.",
                'vencimiento', 'danger', 'nc', nc.id)

# ── Context Processor (datos globales para templates) ──────────────

@app.context_processor
def inject_globals():
    notif_count = 0
    if current_user.is_authenticated:
        notif_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    return dict(notif_count=notif_count, today=date.today())

# ── Auth Routes ────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email, active=True).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Email o contraseña incorrectos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ── Dashboard ──────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    # Stats
    total_docs = Document.query.filter_by(status='vigente').count()
    docs_expired = Document.query.filter(Document.next_review_date < today, Document.status == 'vigente').count()
    docs_warning = Document.query.filter(Document.next_review_date.between(today, today + timedelta(days=30)),
                                          Document.status == 'vigente').count()
    open_ncs = NonConformity.query.filter(NonConformity.status.in_(['abierta', 'en_tratamiento'])).count()
    ncs_overdue = NonConformity.query.filter(NonConformity.due_date < today,
                                              NonConformity.status.in_(['abierta', 'en_tratamiento'])).count()
    open_claims = CustomerClaim.query.filter(CustomerClaim.status.in_(['recibido', 'en_investigacion'])).count()
    upcoming_audits = Audit.query.filter(Audit.scheduled_date >= today, Audit.status == 'programada').count()
    objectives = QualityObjective.query.filter_by(status='en_curso').all()
    # Recent activity
    recent_docs = Document.query.order_by(Document.created_at.desc()).limit(5).all()
    recent_ncs = NonConformity.query.order_by(NonConformity.raised_at.desc()).limit(5).all()
    recent_claims = CustomerClaim.query.order_by(CustomerClaim.received_at.desc()).limit(5).all()
    notifications = Notification.query.filter_by(user_id=current_user.id, read=False).order_by(
        Notification.created_at.desc()).limit(10).all()

    return render_template('dashboard.html',
        total_docs=total_docs, docs_expired=docs_expired, docs_warning=docs_warning,
        open_ncs=open_ncs, ncs_overdue=ncs_overdue, open_claims=open_claims,
        upcoming_audits=upcoming_audits, objectives=objectives,
        recent_docs=recent_docs, recent_ncs=recent_ncs, recent_claims=recent_claims,
        notifications=notifications)

# ── Documents ──────────────────────────────────────────────────────

@app.route('/documentos')
@login_required
def documents():
    area_filter = request.args.get('area')
    type_filter = request.args.get('type')
    status_filter = request.args.get('status')
    q = Document.query
    if area_filter:
        q = q.join(Area).filter(Area.code == area_filter)
    if type_filter:
        q = q.join(DocumentType).filter(DocumentType.code == type_filter)
    if status_filter:
        q = q.filter(Document.status == status_filter)
    docs = q.order_by(Document.code).all()
    areas = Area.query.order_by(Area.code).all()
    doc_types = DocumentType.query.order_by(DocumentType.code).all()
    return render_template('documents.html', docs=docs, areas=areas, doc_types=doc_types,
                           area_filter=area_filter, type_filter=type_filter, status_filter=status_filter)

@app.route('/documentos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def document_new():
    if request.method == 'POST':
        doc = Document(
            code=request.form['code'],
            title=request.form['title'],
            type_id=int(request.form['type_id']),
            area_id=int(request.form['area_id']),
            status=request.form.get('status', 'borrador'),
            content=request.form.get('content', ''),
            drive_url=request.form.get('drive_url', ''),
            created_by=current_user.id,
            next_review_date=datetime.strptime(request.form['next_review_date'], '%Y-%m-%d').date() if request.form.get('next_review_date') else None
        )
        db.session.add(doc)
        db.session.commit()
        flash(f'Documento {doc.code} creado.', 'success')
        return redirect(url_for('documents'))
    areas = Area.query.order_by(Area.code).all()
    doc_types = DocumentType.query.order_by(DocumentType.code).all()
    return render_template('document_form.html', doc=None, areas=areas, doc_types=doc_types)

@app.route('/documentos/<int:doc_id>')
@login_required
def document_detail(doc_id):
    doc = Document.query.get_or_404(doc_id)
    return render_template('document_detail.html', doc=doc)

@app.route('/documentos/<int:doc_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def document_edit(doc_id):
    doc = Document.query.get_or_404(doc_id)
    if request.method == 'POST':
        old_version = doc.version
        doc.code = request.form['code']
        doc.title = request.form['title']
        doc.type_id = int(request.form['type_id'])
        doc.area_id = int(request.form['area_id'])
        doc.status = request.form.get('status', doc.status)
        doc.content = request.form.get('content', '')
        doc.drive_url = request.form.get('drive_url', '')
        if request.form.get('next_review_date'):
            doc.next_review_date = datetime.strptime(request.form['next_review_date'], '%Y-%m-%d').date()
        if request.form.get('new_version'):
            doc.version += 1
            version = DocumentVersion(document_id=doc.id, version=doc.version,
                                       changes=request.form.get('changes', ''), created_by=current_user.id)
            db.session.add(version)
        db.session.commit()
        flash(f'Documento {doc.code} actualizado.', 'success')
        return redirect(url_for('document_detail', doc_id=doc.id))
    areas = Area.query.order_by(Area.code).all()
    doc_types = DocumentType.query.order_by(DocumentType.code).all()
    return render_template('document_form.html', doc=doc, areas=areas, doc_types=doc_types)

# ── Quality Objectives ────────────────────────────────────────────

@app.route('/objetivos')
@login_required
def objectives():
    objs = QualityObjective.query.order_by(QualityObjective.area_id, QualityObjective.code).all()
    areas = Area.query.all()
    return render_template('objectives.html', objectives=objs, areas=areas)

@app.route('/objetivos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def objective_new():
    if request.method == 'POST':
        obj = QualityObjective(
            code=request.form.get('code', ''),
            name=request.form['name'],
            description=request.form.get('description', ''),
            area_id=int(request.form['area_id']),
            indicator=request.form.get('indicator', ''),
            target=request.form.get('target', ''),
            unit=request.form.get('unit', ''),
            frequency=request.form.get('frequency', 'mensual'),
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None,
            responsible_id=int(request.form['responsible_id']) if request.form.get('responsible_id') else None
        )
        db.session.add(obj)
        db.session.commit()
        flash('Objetivo creado.', 'success')
        return redirect(url_for('objectives'))
    areas = Area.query.all()
    users = User.query.filter_by(active=True).all()
    return render_template('objective_form.html', obj=None, areas=areas, users=users)

@app.route('/objetivos/<int:obj_id>')
@login_required
def objective_detail(obj_id):
    obj = QualityObjective.query.get_or_404(obj_id)
    return render_template('objective_detail.html', obj=obj)

@app.route('/objetivos/<int:obj_id>/medicion', methods=['POST'])
@login_required
def objective_measure(obj_id):
    obj = QualityObjective.query.get_or_404(obj_id)
    m = ObjectiveMeasurement(
        objective_id=obj.id,
        date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(),
        value=request.form['value'],
        notes=request.form.get('notes', ''),
        recorded_by=current_user.id
    )
    obj.current_value = request.form['value']
    db.session.add(m)
    db.session.commit()
    flash('Medición registrada.', 'success')
    return redirect(url_for('objective_detail', obj_id=obj.id))

# ── Non-Conformities ──────────────────────────────────────────────

@app.route('/no-conformidades')
@login_required
def non_conformities():
    status_filter = request.args.get('status')
    q = NonConformity.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    ncs = q.order_by(NonConformity.raised_at.desc()).all()
    return render_template('non_conformities.html', ncs=ncs, status_filter=status_filter)

@app.route('/no-conformidades/nueva', methods=['GET', 'POST'])
@login_required
def nc_new():
    if request.method == 'POST':
        # Auto-generate code
        count = NonConformity.query.count() + 1
        code = f"NC-{datetime.now().year}-{count:03d}"
        nc = NonConformity(
            code=code,
            title=request.form['title'],
            description=request.form.get('description', ''),
            nc_type=request.form.get('nc_type', 'menor'),
            source=request.form.get('source', ''),
            area_id=int(request.form['area_id']),
            raised_by=current_user.id,
            assigned_to=int(request.form['assigned_to']) if request.form.get('assigned_to') else None,
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None
        )
        db.session.add(nc)
        db.session.commit()
        if nc.assigned_to:
            send_notification(nc.assigned_to, f"Nueva NC asignada: {nc.code}",
                f"Se te asignó la no conformidad {nc.code}: {nc.title}. Fecha límite: {nc.due_date}.",
                'tarea', 'warning', 'nc', nc.id)
        flash(f'No conformidad {nc.code} creada.', 'success')
        return redirect(url_for('non_conformities'))
    areas = Area.query.all()
    users = User.query.filter_by(active=True).all()
    return render_template('nc_form.html', nc=None, areas=areas, users=users)

@app.route('/no-conformidades/<int:nc_id>', methods=['GET', 'POST'])
@login_required
def nc_detail(nc_id):
    nc = NonConformity.query.get_or_404(nc_id)
    if request.method == 'POST':
        nc.root_cause = request.form.get('root_cause', nc.root_cause)
        nc.corrective_action = request.form.get('corrective_action', nc.corrective_action)
        nc.preventive_action = request.form.get('preventive_action', nc.preventive_action)
        nc.verification = request.form.get('verification', nc.verification)
        new_status = request.form.get('status', nc.status)
        if new_status != nc.status:
            nc.status = new_status
            if new_status in ('cerrada', 'verificada'):
                nc.closed_at = datetime.utcnow()
        db.session.commit()
        flash('No conformidad actualizada.', 'success')
        return redirect(url_for('nc_detail', nc_id=nc.id))
    return render_template('nc_detail.html', nc=nc)

# ── Customer Claims ────────────────────────────────────────────────

@app.route('/reclamos')
@login_required
def claims():
    status_filter = request.args.get('status')
    q = CustomerClaim.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    claims_list = q.order_by(CustomerClaim.received_at.desc()).all()
    return render_template('claims.html', claims=claims_list, status_filter=status_filter)

@app.route('/reclamos/nuevo', methods=['GET', 'POST'])
@login_required
def claim_new():
    if request.method == 'POST':
        count = CustomerClaim.query.count() + 1
        code = f"REC-{datetime.now().year}-{count:03d}"
        claim = CustomerClaim(
            code=code,
            customer_name=request.form['customer_name'],
            product=request.form.get('product', ''),
            lot_number=request.form.get('lot_number', ''),
            description=request.form['description'],
            claim_type=request.form.get('claim_type', ''),
            severity=request.form.get('severity', 'media'),
            received_by=current_user.id,
            assigned_to=int(request.form['assigned_to']) if request.form.get('assigned_to') else None,
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None
        )
        db.session.add(claim)
        db.session.commit()
        flash(f'Reclamo {claim.code} registrado.', 'success')
        return redirect(url_for('claims'))
    users = User.query.filter_by(active=True).all()
    return render_template('claim_form.html', claim=None, users=users)

@app.route('/reclamos/<int:claim_id>', methods=['GET', 'POST'])
@login_required
def claim_detail(claim_id):
    claim = CustomerClaim.query.get_or_404(claim_id)
    if request.method == 'POST':
        claim.investigation = request.form.get('investigation', claim.investigation)
        claim.resolution = request.form.get('resolution', claim.resolution)
        new_status = request.form.get('status', claim.status)
        if new_status != claim.status:
            claim.status = new_status
            if new_status == 'cerrado':
                claim.closed_at = datetime.utcnow()
        db.session.commit()
        flash('Reclamo actualizado.', 'success')
    return render_template('claim_detail.html', claim=claim)

# ── Audits ────────────────────────────────────────────────────────

@app.route('/auditorias')
@login_required
def audits():
    audits_list = Audit.query.order_by(Audit.scheduled_date.desc()).all()
    return render_template('audits.html', audits=audits_list)

@app.route('/auditorias/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def audit_new():
    if request.method == 'POST':
        count = Audit.query.count() + 1
        code = f"AUD-{datetime.now().year}-{count:03d}"
        audit = Audit(
            code=code,
            audit_type=request.form['audit_type'],
            area_id=int(request.form['area_id']) if request.form.get('area_id') else None,
            scheduled_date=datetime.strptime(request.form['scheduled_date'], '%Y-%m-%d').date(),
            auditor_id=int(request.form['auditor_id']) if request.form.get('auditor_id') else None,
            scope=request.form.get('scope', '')
        )
        db.session.add(audit)
        db.session.commit()
        flash(f'Auditoría {audit.code} programada.', 'success')
        return redirect(url_for('audits'))
    areas = Area.query.all()
    users = User.query.filter_by(active=True).all()
    return render_template('audit_form.html', audit=None, areas=areas, users=users)

@app.route('/auditorias/<int:audit_id>', methods=['GET', 'POST'])
@login_required
def audit_detail(audit_id):
    audit = Audit.query.get_or_404(audit_id)
    if request.method == 'POST':
        audit.findings = request.form.get('findings', audit.findings)
        audit.conclusions = request.form.get('conclusions', audit.conclusions)
        new_status = request.form.get('status', audit.status)
        if new_status != audit.status:
            audit.status = new_status
            if new_status == 'completada':
                audit.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Auditoría actualizada.', 'success')
    return render_template('audit_detail.html', audit=audit)

# ── Formularios ────────────────────────────────────────────────────

@app.route('/formularios')
@login_required
def forms():
    templates = FormTemplate.query.filter_by(active=True).order_by(FormTemplate.title).all()
    return render_template('forms.html', templates=templates)

@app.route('/formularios/<int:tmpl_id>/completar', methods=['GET', 'POST'])
@login_required
def form_fill(tmpl_id):
    tmpl = FormTemplate.query.get_or_404(tmpl_id)
    if request.method == 'POST':
        data = {}
        for field in tmpl.fields:
            data[field['name']] = request.form.get(field['name'], '')
        submission = FormSubmission(
            template_id=tmpl.id,
            data_json=json.dumps(data, ensure_ascii=False),
            submitted_by=current_user.id
        )
        db.session.add(submission)
        db.session.commit()
        flash('Formulario enviado.', 'success')
        return redirect(url_for('form_submissions', tmpl_id=tmpl.id))
    return render_template('form_fill.html', tmpl=tmpl)

@app.route('/formularios/<int:tmpl_id>/registros')
@login_required
def form_submissions(tmpl_id):
    tmpl = FormTemplate.query.get_or_404(tmpl_id)
    subs = FormSubmission.query.filter_by(template_id=tmpl.id).order_by(FormSubmission.submitted_at.desc()).all()
    return render_template('form_submissions.html', tmpl=tmpl, submissions=subs)

# ── Notifications ──────────────────────────────────────────────────

@app.route('/notificaciones')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()).limit(50).all()
    return render_template('notifications.html', notifications=notifs)

@app.route('/notificaciones/leer/<int:notif_id>')
@login_required
def notification_read(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id == current_user.id:
        notif.read = True
        db.session.commit()
    # Redirect to entity if possible
    if notif.entity_type == 'document' and notif.entity_id:
        return redirect(url_for('document_detail', doc_id=notif.entity_id))
    elif notif.entity_type == 'nc' and notif.entity_id:
        return redirect(url_for('nc_detail', nc_id=notif.entity_id))
    return redirect(url_for('notifications'))

@app.route('/notificaciones/leer-todas')
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    return redirect(url_for('notifications'))

# ── Users (Admin) ──────────────────────────────────────────────────

@app.route('/usuarios')
@login_required
@admin_required
def users():
    users_list = User.query.order_by(User.name).all()
    return render_template('users.html', users=users_list)

@app.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def user_new():
    if request.method == 'POST':
        user = User(
            email=request.form['email'],
            name=request.form['name'],
            role=request.form.get('role', 'usuario'),
            area_id=int(request.form['area_id']) if request.form.get('area_id') else None
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        flash(f'Usuario {user.name} creado.', 'success')
        return redirect(url_for('users'))
    areas = Area.query.all()
    return render_template('user_form.html', user=None, areas=areas)

@app.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form['email']
        user.role = request.form.get('role', user.role)
        user.area_id = int(request.form['area_id']) if request.form.get('area_id') else None
        user.active = 'active' in request.form
        if request.form.get('password'):
            user.set_password(request.form['password'])
        db.session.commit()
        flash(f'Usuario {user.name} actualizado.', 'success')
        return redirect(url_for('users'))
    areas = Area.query.all()
    return render_template('user_form.html', user=user, areas=areas)

# ── API Endpoints ──────────────────────────────────────────────────

@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    today = date.today()
    return jsonify({
        'docs_vigentes': Document.query.filter_by(status='vigente').count(),
        'docs_vencidos': Document.query.filter(Document.next_review_date < today, Document.status == 'vigente').count(),
        'ncs_abiertas': NonConformity.query.filter(NonConformity.status.in_(['abierta', 'en_tratamiento'])).count(),
        'reclamos_abiertos': CustomerClaim.query.filter(CustomerClaim.status.in_(['recibido', 'en_investigacion'])).count(),
        'auditorias_pendientes': Audit.query.filter(Audit.scheduled_date >= today, Audit.status == 'programada').count(),
    })

@app.route('/api/check-deadlines')
@login_required
@admin_required
def api_check_deadlines():
    check_deadlines()
    return jsonify({'status': 'ok', 'message': 'Verificación de vencimientos ejecutada.'})

# ── Init DB ────────────────────────────────────────────────────────

def init_db():
    """Inicializa la BD con datos de Agrefert"""
    db.create_all()
    # Solo si está vacía
    if User.query.count() > 0:
        return

    # Áreas
    areas_data = [
        ('DIR', 'Dirección General'),
        ('COM', 'Comercial'),
        ('PRO', 'Producción'),
        ('CPR', 'Compras y Proveedores'),
        ('RHH', 'Recursos Humanos'),
        ('SGC', 'Sistema de Gestión ISO'),
        ('MAN', 'Mantenimiento'),
        ('ADM', 'Administración y Finanzas'),
        ('BAC', 'Bactools'),
    ]
    areas = {}
    for code, name in areas_data:
        a = Area(code=code, name=name)
        db.session.add(a)
        areas[code] = a
    db.session.flush()

    # Tipos de documento
    doc_types_data = [
        ('MC', 'Manual de Calidad', 'Manual principal del SGC'),
        ('PO', 'Política', 'Políticas de calidad y organizacionales'),
        ('PG', 'Procedimiento General', 'Procedimientos documentados del SGC'),
        ('IT', 'Instructivo', 'Instrucciones de trabajo detalladas'),
        ('FO', 'Formulario', 'Plantillas para registros'),
        ('RE', 'Registro', 'Registros completados'),
        ('PE', 'Plan', 'Planes de calidad, auditoría, etc.'),
        ('DE', 'Documento Externo', 'Normas, reglamentaciones, etc.'),
    ]
    doc_types = {}
    for code, name, desc in doc_types_data:
        dt = DocumentType(code=code, name=name, description=desc)
        db.session.add(dt)
        doc_types[code] = dt
    db.session.flush()

    # Admin user
    admin = User(email='federico@agrefert.com', name='Federico Muñoz', role='admin')
    admin.area_id = areas['DIR'].id
    admin.set_password('admin2026')
    db.session.add(admin)

    # Team users
    team = [
        ('nicolas.hernandez@agrefert.com', 'Nicolás Hernández', 'responsable', 'COM'),
        ('facundo.tomasella@agrefert.com', 'Facundo Tomasella', 'responsable', 'ADM'),
        ('christian.insua@agrefert.com', 'Christian Insúa', 'responsable', 'PRO'),
        ('luciana.posco@agrefert.com', 'Luciana Posco', 'usuario', 'ADM'),
        ('agustin.raffa@agrefert.com', 'Agustín Raffa', 'usuario', 'COM'),
        ('ricardo.bavasso@agrefert.com', 'Ricardo Bavasso', 'auditor', 'SGC'),
        ('franco.ziraldo@bactools.com', 'Franco Ziraldo', 'usuario', 'BAC'),
        ('walter.ramirez@bactools.com', 'Walter Ramírez', 'usuario', 'BAC'),
    ]
    for email, name, role, area_code in team:
        u = User(email=email, name=name, role=role, area_id=areas[area_code].id)
        u.set_password('agrefert2026')
        db.session.add(u)
    db.session.flush()

    # Documentos del SGC de Agrefert (estructura real)
    docs_data = [
        # Manual y Políticas
        ('MC-SGC-001', 'Manual de Calidad', 'MC', 'SGC', 'vigente', 2, '2026-12-31',
         'https://docs.google.com/document/d/1VeBtVe-4gfSC81jhTdZNUyiifhR46cYNiYme8LIKRmo/edit'),
        ('PO-DIR-001', 'Política de Calidad', 'PO', 'DIR', 'vigente', 3, '2027-03-01', ''),
        ('PO-DIR-002', 'Política de Compras, Gastos y Rendiciones', 'PO', 'DIR', 'vigente', 1, '2027-03-01',
         'https://agrefert.atlassian.net/wiki/spaces/AGREFERT/pages/948076545'),
        # Procedimientos de Dirección
        ('PG-DIR-001', 'Revisión por la Dirección', 'PG', 'DIR', 'vigente', 2, '2026-09-30', ''),
        ('PG-DIR-002', 'Planificación Estratégica y Objetivos de Calidad', 'PG', 'DIR', 'vigente', 2, '2026-09-30', ''),
        ('PG-DIR-003', 'Análisis del Contexto y Partes Interesadas', 'PG', 'DIR', 'vigente', 1, '2026-12-31', ''),
        ('PG-DIR-004', 'Gestión de Riesgos y Oportunidades', 'PG', 'DIR', 'vigente', 1, '2026-12-31',
         'https://docs.google.com/document/d/1AcbuAKxG5xFD3lQvtHDgwvdVC8TdFVlCoslsasGMBsE/edit'),
        # Procedimientos Comerciales
        ('PG-COM-001', 'Gestión Comercial y Ventas', 'PG', 'COM', 'vigente', 2, '2026-09-30', ''),
        ('PG-COM-002', 'Gestión de Reclamos de Clientes', 'PG', 'COM', 'vigente', 2, '2026-09-30', ''),
        ('PG-COM-003', 'Satisfacción del Cliente', 'PG', 'COM', 'vigente', 1, '2026-12-31', ''),
        # Procedimientos de Producción
        ('PG-PRO-001', 'Control de Producción', 'PG', 'PRO', 'vigente', 3, '2026-09-30', ''),
        ('PG-PRO-002', 'Control de Producto No Conforme', 'PG', 'PRO', 'vigente', 2, '2026-09-30', ''),
        ('PG-PRO-003', 'Trazabilidad de Productos', 'PG', 'PRO', 'vigente', 2, '2026-09-30', ''),
        ('PG-PRO-004', 'Inspección y Ensayo', 'PG', 'PRO', 'vigente', 1, '2026-12-31', ''),
        ('PG-PRO-005', 'Control de Equipos de Medición', 'PG', 'PRO', 'vigente', 1, '2026-12-31', ''),
        # Procedimientos Compras
        ('PG-CPR-001', 'Compras y Evaluación de Proveedores', 'PG', 'CPR', 'vigente', 2, '2026-09-30', ''),
        ('PG-CPR-002', 'Recepción e Inspección de Materias Primas', 'PG', 'CPR', 'vigente', 1, '2026-12-31', ''),
        # Procedimientos RRHH
        ('PG-RHH-001', 'Selección e Ingreso de Personal', 'PG', 'RHH', 'vigente', 1, '2026-12-31', ''),
        ('PG-RHH-002', 'Capacitación y Competencias', 'PG', 'RHH', 'vigente', 1, '2026-12-31', ''),
        ('PG-RHH-003', 'Evaluación de Desempeño', 'PG', 'RHH', 'vigente', 1, '2026-12-31', ''),
        # Procedimientos SGC
        ('PG-SGC-001', 'Control de Documentos y Registros', 'PG', 'SGC', 'vigente', 3, '2026-09-30', ''),
        ('PG-SGC-002', 'Auditorías Internas', 'PG', 'SGC', 'vigente', 2, '2026-09-30', ''),
        ('PG-SGC-003', 'Acciones Correctivas y Preventivas', 'PG', 'SGC', 'vigente', 2, '2026-09-30', ''),
        ('PG-SGC-004', 'Mejora Continua', 'PG', 'SGC', 'vigente', 1, '2026-12-31', ''),
        # Procedimientos Mantenimiento
        ('PG-MAN-001', 'Mantenimiento Preventivo y Correctivo', 'PG', 'MAN', 'vigente', 1, '2026-12-31', ''),
        # Instructivos Producción
        ('IT-PRO-001', 'Producción de Mezclas Sólidas (Chacarero)', 'IT', 'PRO', 'vigente', 2, '2026-09-30', ''),
        ('IT-PRO-002', 'Producción de Fertilizantes Líquidos (Zurko)', 'IT', 'PRO', 'vigente', 2, '2026-09-30', ''),
        ('IT-PRO-003', 'Despacho de Producto Terminado', 'IT', 'PRO', 'vigente', 1, '2026-12-31', ''),
        ('IT-PRO-004', 'Embolsado de Monoproducto', 'IT', 'PRO', 'vigente', 1, '2026-12-31', ''),
        ('IT-PRO-005', 'Extracción de Muestras para Laboratorio', 'IT', 'PRO', 'vigente', 1, '2026-12-31', ''),
        # Instructivos Comerciales
        ('IT-COM-001', 'Alta de Nuevo Cliente', 'IT', 'COM', 'vigente', 1, '2026-12-31', ''),
        ('IT-COM-002', 'Solicitud de Cupos de Carga', 'IT', 'COM', 'vigente', 1, '2026-12-31', ''),
        # Formularios
        ('FO-PRO-001', 'Registro de Trazabilidad', 'FO', 'PRO', 'vigente', 2, '2026-12-31',
         'https://forms.gle/RwizyKvSQomupJFr8'),
        ('FO-PRO-002', 'Parte de Producción Diario', 'FO', 'PRO', 'vigente', 1, '2026-12-31', ''),
        ('FO-PRO-003', 'Control de Calibración de Equipos', 'FO', 'PRO', 'vigente', 1, '2026-12-31', ''),
        ('FO-COM-001', 'Formulario de Reclamo de Cliente', 'FO', 'COM', 'vigente', 2, '2026-12-31', ''),
        ('FO-COM-002', 'Legajo de Alta de Cliente', 'FO', 'COM', 'vigente', 1, '2026-12-31', ''),
        ('FO-CPR-001', 'Evaluación de Proveedores', 'FO', 'CPR', 'vigente', 1, '2026-12-31', ''),
        ('FO-CPR-002', 'Inspección de Recepción de Materias Primas', 'FO', 'CPR', 'vigente', 1, '2026-12-31', ''),
        ('FO-RHH-001', 'Legajo de Ingreso de Personal', 'FO', 'RHH', 'vigente', 1, '2026-12-31', ''),
        ('FO-RHH-002', 'Registro de Capacitación', 'FO', 'RHH', 'vigente', 1, '2026-12-31', ''),
        ('FO-SGC-001', 'Lista Maestra de Documentos', 'FO', 'SGC', 'vigente', 2, '2026-12-31', ''),
        ('FO-SGC-002', 'Registro de Auditoría Interna', 'FO', 'SGC', 'vigente', 1, '2026-12-31', ''),
        ('FO-SGC-003', 'Registro de Acción Correctiva', 'FO', 'SGC', 'vigente', 1, '2026-12-31', ''),
        ('FO-SGC-004', 'Acta de Revisión por la Dirección', 'FO', 'SGC', 'vigente', 1, '2026-12-31', ''),
        ('FO-MAN-001', 'Orden de Trabajo de Mantenimiento', 'FO', 'MAN', 'vigente', 1, '2026-12-31', ''),
    ]
    for code, title, type_code, area_code, status, version, review_date, url in docs_data:
        doc = Document(
            code=code, title=title, type_id=doc_types[type_code].id,
            area_id=areas[area_code].id, version=version, status=status,
            drive_url=url, created_by=admin.id,
            next_review_date=datetime.strptime(review_date, '%Y-%m-%d').date()
        )
        db.session.add(doc)

    # Objetivos de Calidad 2026
    objectives_data = [
        ('OC-01', 'Rentabilidad y mix de productos', 'Maximizar la rentabilidad mediante optimización del mix',
         'DIR', 'Participación de productos propios sobre volumen total', '≥ 70%', '%', 'mensual', '2027-03-31'),
        ('OC-02', 'DSO Zurko', 'Reducir plazo de cobranza línea Zurko',
         'ADM', 'Días de cobranza Zurko', '< 100 días', 'días', 'mensual', '2027-03-31'),
        ('OC-03', 'DSO Chacarero', 'Reducir plazo de cobranza línea Chacarero',
         'ADM', 'Días de cobranza Chacarero', '< 60 días', 'días', 'mensual', '2027-03-31'),
        ('OC-04', 'DSO Commodities', 'Reducir plazo de cobranza Commodities',
         'ADM', 'Días de cobranza Commodities', '< 30 días', 'días', 'mensual', '2027-03-31'),
        ('OC-05', 'Deuda vencida', 'Controlar nivel de deuda vencida',
         'ADM', 'Deuda vencida sobre facturación', '< 3%', '%', 'mensual', '2027-03-31'),
        ('OC-06', 'Volumen sostenible', 'Sostener actividad priorizando rentabilidad',
         'COM', 'Toneladas vendidas', '100.000 - 115.000 t', 't', 'mensual', '2027-03-31'),
        ('OC-07', 'Reclamos de calidad', 'Mantener bajo nivel de reclamos',
         'PRO', 'Reclamos sobre volumen operado', '< 1%', '%', 'mensual', '2027-03-31'),
        ('OC-08', 'OTIF', 'Entrega a tiempo y completa',
         'PRO', 'Porcentaje de entregas OTIF', '≥ 95%', '%', 'mensual', '2027-03-31'),
        ('OC-09', 'Exactitud de inventario', 'Precisión de inventario físico vs sistema',
         'PRO', 'Exactitud de inventario', '≥ 98%', '%', 'mensual', '2027-03-31'),
        ('OC-10', 'Cumplimiento plan de abastecimiento', 'Ejecutar plan de compras',
         'CPR', 'Cumplimiento plan', '≥ 90%', '%', 'trimestral', '2027-03-31'),
        ('OC-11', 'Satisfacción del cliente', 'Medir y mejorar satisfacción',
         'COM', 'Encuesta de satisfacción', '≥ 8/10', 'puntos', 'semestral', '2027-03-31'),
        ('OC-12', 'Rotación posiciones clave', 'Retener talento crítico',
         'RHH', 'Rotación voluntaria posiciones clave', '< 10%', '%', 'anual', '2027-03-31'),
    ]
    for code, name, desc, area_code, indicator, target, unit, freq, due in objectives_data:
        obj = QualityObjective(
            code=code, name=name, description=desc, area_id=areas[area_code].id,
            indicator=indicator, target=target, unit=unit, frequency=freq,
            due_date=datetime.strptime(due, '%Y-%m-%d').date(),
            responsible_id=admin.id
        )
        db.session.add(obj)

    # Form templates de ejemplo
    templates_data = [
        ('Registro de Trazabilidad', 'PRO', [
            {'name': 'fecha', 'label': 'Fecha', 'type': 'date', 'required': True},
            {'name': 'producto', 'label': 'Producto', 'type': 'select', 'required': True,
             'options': ['Zurko NS', 'Zurko Max', 'Zurko 28-5', 'ANSUL', 'Urea Azufrada', 'Nitro C', 'Mezcla NPS']},
            {'name': 'lote', 'label': 'Número de Lote', 'type': 'text', 'required': True},
            {'name': 'cantidad_kg', 'label': 'Cantidad (kg)', 'type': 'number', 'required': True},
            {'name': 'materias_primas', 'label': 'Materias Primas Utilizadas', 'type': 'textarea', 'required': True},
            {'name': 'operador', 'label': 'Operador', 'type': 'text', 'required': True},
            {'name': 'aprobado', 'label': 'Control de Calidad Aprobado', 'type': 'select', 'required': True,
             'options': ['Sí', 'No', 'Pendiente']},
            {'name': 'observaciones', 'label': 'Observaciones', 'type': 'textarea', 'required': False},
        ]),
        ('Parte de Producción Diario', 'PRO', [
            {'name': 'fecha', 'label': 'Fecha', 'type': 'date', 'required': True},
            {'name': 'turno', 'label': 'Turno', 'type': 'select', 'required': True, 'options': ['Mañana', 'Tarde']},
            {'name': 'linea', 'label': 'Línea', 'type': 'select', 'required': True,
             'options': ['Sólidos - Mezcladora', 'Líquidos - Reactor 1', 'Líquidos - Reactor 2', 'Embolsado']},
            {'name': 'producto', 'label': 'Producto', 'type': 'text', 'required': True},
            {'name': 'cantidad_producida', 'label': 'Cantidad Producida (t)', 'type': 'number', 'required': True},
            {'name': 'paradas', 'label': 'Paradas / Incidentes', 'type': 'textarea', 'required': False},
            {'name': 'supervisor', 'label': 'Supervisor', 'type': 'text', 'required': True},
        ]),
        ('Evaluación de Proveedores', 'CPR', [
            {'name': 'fecha', 'label': 'Fecha de Evaluación', 'type': 'date', 'required': True},
            {'name': 'proveedor', 'label': 'Proveedor', 'type': 'text', 'required': True},
            {'name': 'producto_servicio', 'label': 'Producto/Servicio', 'type': 'text', 'required': True},
            {'name': 'calidad', 'label': 'Calidad del producto (1-10)', 'type': 'number', 'required': True},
            {'name': 'cumplimiento_entrega', 'label': 'Cumplimiento de entrega (1-10)', 'type': 'number', 'required': True},
            {'name': 'precio', 'label': 'Competitividad de precio (1-10)', 'type': 'number', 'required': True},
            {'name': 'servicio', 'label': 'Servicio post-venta (1-10)', 'type': 'number', 'required': True},
            {'name': 'resultado', 'label': 'Resultado', 'type': 'select', 'required': True,
             'options': ['Aprobado', 'Aprobado Condicional', 'No Aprobado']},
            {'name': 'observaciones', 'label': 'Observaciones', 'type': 'textarea', 'required': False},
        ]),
        ('Reclamo de Cliente', 'COM', [
            {'name': 'fecha', 'label': 'Fecha del Reclamo', 'type': 'date', 'required': True},
            {'name': 'cliente', 'label': 'Cliente', 'type': 'text', 'required': True},
            {'name': 'producto', 'label': 'Producto Reclamado', 'type': 'text', 'required': True},
            {'name': 'lote', 'label': 'Número de Lote', 'type': 'text', 'required': False},
            {'name': 'tipo', 'label': 'Tipo de Reclamo', 'type': 'select', 'required': True,
             'options': ['Calidad de producto', 'Logística', 'Servicio', 'Documentación', 'Otro']},
            {'name': 'descripcion', 'label': 'Descripción del Reclamo', 'type': 'textarea', 'required': True},
            {'name': 'severidad', 'label': 'Severidad', 'type': 'select', 'required': True,
             'options': ['Baja', 'Media', 'Alta', 'Crítica']},
            {'name': 'accion_inmediata', 'label': 'Acción Inmediata Tomada', 'type': 'textarea', 'required': False},
        ]),
        ('Inspección de Recepción de Materias Primas', 'CPR', [
            {'name': 'fecha', 'label': 'Fecha de Recepción', 'type': 'date', 'required': True},
            {'name': 'proveedor', 'label': 'Proveedor', 'type': 'text', 'required': True},
            {'name': 'producto', 'label': 'Producto', 'type': 'text', 'required': True},
            {'name': 'remito', 'label': 'Nro. de Remito', 'type': 'text', 'required': True},
            {'name': 'cantidad', 'label': 'Cantidad (t)', 'type': 'number', 'required': True},
            {'name': 'estado_embalaje', 'label': 'Estado del Embalaje', 'type': 'select', 'required': True,
             'options': ['Bueno', 'Regular', 'Malo']},
            {'name': 'coincide_remito', 'label': 'Coincide con Remito', 'type': 'select', 'required': True,
             'options': ['Sí', 'No']},
            {'name': 'muestra_laboratorio', 'label': 'Se tomó muestra para laboratorio', 'type': 'select', 'required': True,
             'options': ['Sí', 'No']},
            {'name': 'resultado', 'label': 'Resultado Inspección', 'type': 'select', 'required': True,
             'options': ['Aprobado', 'Rechazado', 'Aprobado Condicional']},
            {'name': 'observaciones', 'label': 'Observaciones', 'type': 'textarea', 'required': False},
        ]),
    ]
    for title, area_code, fields in templates_data:
        tmpl = FormTemplate(
            title=title, area_id=areas[area_code].id,
            fields_json=json.dumps(fields, ensure_ascii=False)
        )
        db.session.add(tmpl)

    db.session.commit()
    print("✅ Base de datos inicializada con datos de Agrefert.")

# ── Run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
