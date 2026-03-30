"""
Modelos de Base de Datos — SGC Agrefert (ISO 9001:2015)
"""
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

# ── Usuarios y Áreas ──────────────────────────────────────────────

class Area(db.Model):
    __tablename__ = 'areas'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)  # DIR, COM, PRO, CPR, RHH, SGC, MAN
    name = db.Column(db.String(100), nullable=False)
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    users = db.relationship('User', backref='area', foreign_keys='User.area_id', lazy=True)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='usuario')  # admin, responsable, auditor, usuario
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ── Documentos del SGC ─────────────────────────────────────────────

class DocumentType(db.Model):
    __tablename__ = 'document_types'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(5), unique=True, nullable=False)  # PG, IT, FO, RE, MC, PO
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)

class Document(db.Model):
    __tablename__ = 'documents'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)  # e.g., PG-DIR-001
    title = db.Column(db.String(200), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('document_types.id'), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'), nullable=False)
    version = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='borrador')  # borrador, vigente, en_revision, obsoleto
    content = db.Column(db.Text)
    drive_url = db.Column(db.String(500))  # Link al doc en Google Drive
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    next_review_date = db.Column(db.Date)

    doc_type = db.relationship('DocumentType', backref='documents')
    area = db.relationship('Area', backref='documents')
    creator = db.relationship('User', foreign_keys=[created_by])
    approver = db.relationship('User', foreign_keys=[approved_by])
    versions = db.relationship('DocumentVersion', backref='document', lazy=True, order_by='DocumentVersion.version.desc()')

    @property
    def alert_status(self):
        """Semáforo: verde, amarillo, rojo según vencimiento"""
        if not self.next_review_date:
            return 'gris'
        today = date.today()
        days_left = (self.next_review_date - today).days
        if days_left < 0:
            return 'rojo'
        elif days_left <= 30:
            return 'amarillo'
        else:
            return 'verde'

class DocumentVersion(db.Model):
    __tablename__ = 'document_versions'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    changes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User', foreign_keys=[created_by])

# ── Formularios y Registros ────────────────────────────────────────

class FormTemplate(db.Model):
    """Plantilla de formulario ISO (ej: FO-PRO-001 Trazabilidad)"""
    __tablename__ = 'form_templates'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'))
    title = db.Column(db.String(200), nullable=False)
    fields_json = db.Column(db.Text, nullable=False)  # JSON con definición de campos
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    document = db.relationship('Document')
    area = db.relationship('Area')
    submissions = db.relationship('FormSubmission', backref='template', lazy=True)

    @property
    def fields(self):
        return json.loads(self.fields_json) if self.fields_json else []

class FormSubmission(db.Model):
    """Registro completado de un formulario"""
    __tablename__ = 'form_submissions'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_templates.id'), nullable=False)
    data_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pendiente')  # pendiente, aprobado, rechazado
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    comments = db.Column(db.Text)

    submitter = db.relationship('User', foreign_keys=[submitted_by])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    @property
    def data(self):
        return json.loads(self.data_json) if self.data_json else {}

# ── Objetivos de Calidad ──────────────────────────────────────────

class QualityObjective(db.Model):
    __tablename__ = 'quality_objectives'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'))
    indicator = db.Column(db.String(200))
    target = db.Column(db.String(100))
    current_value = db.Column(db.String(100))
    unit = db.Column(db.String(30))
    frequency = db.Column(db.String(30), default='mensual')  # mensual, trimestral, anual
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='en_curso')  # en_curso, cumplido, no_cumplido, suspendido
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    area = db.relationship('Area')
    responsible = db.relationship('User')
    measurements = db.relationship('ObjectiveMeasurement', backref='objective', lazy=True, order_by='ObjectiveMeasurement.date.desc()')

    @property
    def alert_status(self):
        if not self.due_date:
            return 'gris'
        today = date.today()
        days_left = (self.due_date - today).days
        if self.status == 'cumplido':
            return 'verde'
        if days_left < 0:
            return 'rojo'
        elif days_left <= 30:
            return 'amarillo'
        return 'verde'

class ObjectiveMeasurement(db.Model):
    __tablename__ = 'objective_measurements'
    id = db.Column(db.Integer, primary_key=True)
    objective_id = db.Column(db.Integer, db.ForeignKey('quality_objectives.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    value = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    recorder = db.relationship('User')

# ── No Conformidades y Acciones Correctivas ──────────────────────

class NonConformity(db.Model):
    __tablename__ = 'non_conformities'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    nc_type = db.Column(db.String(20), default='menor')  # menor, mayor, observacion, oportunidad_mejora
    source = db.Column(db.String(50))  # auditoria_interna, auditoria_externa, reclamo_cliente, proceso
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'))
    status = db.Column(db.String(20), default='abierta')  # abierta, en_tratamiento, cerrada, verificada
    raised_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    raised_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    due_date = db.Column(db.Date)
    root_cause = db.Column(db.Text)
    corrective_action = db.Column(db.Text)
    preventive_action = db.Column(db.Text)
    verification = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)

    area = db.relationship('Area')
    raiser = db.relationship('User', foreign_keys=[raised_by])
    assignee = db.relationship('User', foreign_keys=[assigned_to])

    @property
    def alert_status(self):
        if self.status in ('cerrada', 'verificada'):
            return 'verde'
        if not self.due_date:
            return 'amarillo'
        today = date.today()
        days_left = (self.due_date - today).days
        if days_left < 0:
            return 'rojo'
        elif days_left <= 15:
            return 'amarillo'
        return 'verde'

# ── Auditorías ──────────────────────────────────────────────────

class Audit(db.Model):
    __tablename__ = 'audits'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    audit_type = db.Column(db.String(30), nullable=False)  # interna, externa, seguimiento
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'))
    scheduled_date = db.Column(db.Date, nullable=False)
    auditor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(20), default='programada')  # programada, en_curso, completada, cancelada
    scope = db.Column(db.Text)
    findings = db.Column(db.Text)
    conclusions = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)

    area = db.relationship('Area')
    auditor = db.relationship('User')

    @property
    def alert_status(self):
        if self.status == 'completada':
            return 'verde'
        if not self.scheduled_date:
            return 'gris'
        today = date.today()
        days_left = (self.scheduled_date - today).days
        if days_left < 0 and self.status == 'programada':
            return 'rojo'
        elif days_left <= 7:
            return 'amarillo'
        return 'verde'

# ── Reclamos de Cliente ──────────────────────────────────────────

class CustomerClaim(db.Model):
    __tablename__ = 'customer_claims'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    customer_name = db.Column(db.String(200), nullable=False)
    product = db.Column(db.String(200))
    lot_number = db.Column(db.String(50))
    description = db.Column(db.Text, nullable=False)
    claim_type = db.Column(db.String(30))  # calidad_producto, logistica, servicio, documentacion
    severity = db.Column(db.String(20), default='media')  # baja, media, alta, critica
    status = db.Column(db.String(20), default='recibido')  # recibido, en_investigacion, resuelto, cerrado
    received_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    due_date = db.Column(db.Date)
    investigation = db.Column(db.Text)
    resolution = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)
    nc_id = db.Column(db.Integer, db.ForeignKey('non_conformities.id'))

    receiver = db.relationship('User', foreign_keys=[received_by])
    assignee = db.relationship('User', foreign_keys=[assigned_to])
    non_conformity = db.relationship('NonConformity')

    @property
    def alert_status(self):
        if self.status == 'cerrado':
            return 'verde'
        if not self.due_date:
            return 'amarillo'
        today = date.today()
        days_left = (self.due_date - today).days
        if days_left < 0:
            return 'rojo'
        elif days_left <= 5:
            return 'amarillo'
        return 'verde'

# ── Notificaciones ──────────────────────────────────────────────

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notif_type = db.Column(db.String(30))  # vencimiento, tarea, alerta, info
    severity = db.Column(db.String(10), default='info')  # info, warning, danger
    entity_type = db.Column(db.String(30))  # document, objective, nc, audit, claim
    entity_id = db.Column(db.Integer)
    read = db.Column(db.Boolean, default=False)
    email_sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='notifications')

# ── Revisión por la Dirección ────────────────────────────────────

class ManagementReview(db.Model):
    __tablename__ = 'management_reviews'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    date = db.Column(db.Date, nullable=False)
    attendees = db.Column(db.Text)
    topics = db.Column(db.Text)
    conclusions = db.Column(db.Text)
    actions = db.Column(db.Text)
    next_review_date = db.Column(db.Date)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User')
