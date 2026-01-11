from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Customer(db.Model):
    __tablename__ = 'customer'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    telegram_id = db.Column(db.String(50), nullable=True)
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    points = db.Column(db.Integer, default=0)
    referral_code = db.Column(db.String(20), unique=True, nullable=False)
    referred_by = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    reset_token = db.Column(db.String(128), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    referrals = db.relationship('Referral', foreign_keys='Referral.referrer_id', backref='referrer', lazy=True)
    appointments = db.relationship('Appointment', backref='customer', lazy=True)
    points_history = db.relationship('PointsHistory', backref='customer', lazy=True)

class Appointment(db.Model):
    __tablename__ = 'appointment'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    service_type = db.Column(db.String(100), nullable=False)
    appointment_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, default=60)  # in minutes
    points_deducted = db.Column(db.Integer, default=10)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, completed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    admin_cancelled = db.Column(db.Boolean, default=False)
    cancellation_reason = db.Column(db.String(200), nullable=True)

class Referral(db.Model):
    __tablename__ = 'referral'
    
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    referred_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    referral_code = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    referred = db.relationship('Customer', foreign_keys=[referred_id], backref='referred_by_record')

class SalonSettings(db.Model):
    __tablename__ = 'salon_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(100), default='HS Salon')
    max_daily_appointments = db.Column(db.Integer, default=10)
    appointment_duration = db.Column(db.Integer, default=60)  # in minutes
    working_hours_start = db.Column(db.String(5), default='09:00')
    working_hours_end = db.Column(db.String(5), default='18:00')
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    telegram_bot_token = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TelegramChat(db.Model):
    __tablename__ = 'telegram_chat'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), nullable=False)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    username = db.Column(db.String(100), nullable=True)
    chat_type = db.Column(db.String(20), nullable=False)  # private, group, channel
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

class PointsHistory(db.Model):
    __tablename__ = 'points_history'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    old_points = db.Column(db.Integer, nullable=False)
    new_points = db.Column(db.Integer, nullable=False)
    difference = db.Column(db.Integer, nullable=False)  # positive for addition, negative for deduction
    reason = db.Column(db.String(255))
    changed_by = db.Column(db.String(50), default='admin')  # 'admin', 'system', 'appointment', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)