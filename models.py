# models.py
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
    
    def __repr__(self):
        return f'<Customer {self.name}>'

class Service(db.Model):
    """Service model for different salon services with durations"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # Duration in minutes
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=True)  # Optional price field
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - fixed backref name to avoid conflict
    appointments = db.relationship('Appointment', back_populates='service', lazy=True)
    
    def __repr__(self):
        return f'<Service {self.name} ({self.duration}min)>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'duration': self.duration,
            'description': self.description,
            'price': self.price,
            'is_active': self.is_active
        }

class Appointment(db.Model):
    __tablename__ = 'appointment'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)
    service_type = db.Column(db.String(100), nullable=False)  # Keep for backward compatibility
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
    
    # Relationships - fixed to use back_populates
    service = db.relationship('Service', back_populates='appointments')
    
    def __repr__(self):
        return f'<Appointment {self.id}: {self.service_type} at {self.appointment_time}>'

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
    
    def __repr__(self):
        return f'<Referral {self.referral_code}>'

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
    off_days = db.relationship('OffDay', backref='salon_settings', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<SalonSettings {self.business_name}>'

class TelegramChat(db.Model):
    __tablename__ = 'telegram_chat'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), nullable=False, unique=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    username = db.Column(db.String(100), nullable=True)
    chat_type = db.Column(db.String(20), nullable=False)  # private, group, channel
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TelegramChat {self.chat_id}>'

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
    
    def __repr__(self):
        return f'<PointsHistory {self.customer_id}: {self.difference}>'

class OffDay(db.Model):
    __tablename__ = 'off_days'
    
    id = db.Column(db.Integer, primary_key=True)
    salon_settings_id = db.Column(db.Integer, db.ForeignKey('salon_settings.id'))
    
    # Type can be: 'weekly' (every week on specific day) or 'specific' (specific dates)
    type = db.Column(db.String(20), nullable=False, default='specific')
    
    # For weekly off days: day_of_week (0=Monday, 6=Sunday)
    day_of_week = db.Column(db.Integer, nullable=True)
    
    # For specific off days: specific_date
    specific_date = db.Column(db.Date, nullable=True)
    
    # Description/reason for off day
    description = db.Column(db.String(200), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        if self.type == 'weekly':
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            return f"Weekly off: {days[self.day_of_week]}"
        else:
            return f"Specific off: {self.specific_date}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'day_of_week': self.day_of_week,
            'specific_date': self.specific_date.isoformat() if self.specific_date else None,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def get_day_name(self):
        """Get day name for weekly off days"""
        if self.type == 'weekly' and self.day_of_week is not None:
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            return days[self.day_of_week]
        return None