import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from datetime import datetime, timedelta, date
from collections import defaultdict
import requests
import json
from sqlalchemy import text


from models import db, Customer, Appointment, Referral, SalonSettings, TelegramChat, PointsHistory, OffDay, Service

from helpers import (
    generate_referral_code, normalize_phone_number, get_date_color,
    get_available_time_slots, award_referral_points, send_telegram_message,
    send_telegram_to_customer, send_appointment_confirmation
)
from config import Config

# =========================
# CREATE APP FIRST
# =========================
app = Flask(__name__)
app.config.from_object(Config)

# =========================
# DATABASE CONFIG (Render-safe)
# =========================
DB_PATH = "/tmp/app.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# =========================
# INIT DB
# =========================
db.init_app(app)

# =========================
# CREATE TABLES
# =========================
with app.app_context():
    try:
        db.create_all()

        if not SalonSettings.query.first():
            default_settings = SalonSettings()
            db.session.add(default_settings)
            db.session.commit()

        # Create services table and add defaults if none exist
        try:
            if not Service.query.first():
                print("📋 Adding default services...")
                default_services = [
                    Service(name='Haircut', duration=45, description='Professional haircut service', price=45.00),
                    Service(name='Hair Coloring', duration=120, description='Full hair coloring', price=120.00),
                    Service(name='Hair Treatment', duration=60, description='Deep conditioning treatment', price=80.00),
                    Service(name='Styling', duration=45, description='Blow dry and styling', price=50.00),
                    Service(name='Perm', duration=150, description='Professional perming service', price=200.00),
                    Service(name='Highlights', duration=120, description='Foil highlights', price=150.00),
                    Service(name="Men's Cut", duration=30, description="Quick men's haircut", price=35.00),
                    Service(name="Children's Cut", duration=30, description='Haircut for children under 12', price=30.00),
                ]
                
                for service in default_services:
                    db.session.add(service)
                
                db.session.commit()
                print("✅ Default services added!")
        except Exception as e:
            print(f"⚠️  Note: Services table setup: {e}")

        print("✅ Database ready!")

    except Exception as e:
        print("❌ Error initializing database:", e)

    
    # Try to set Telegram webhook if token exists
    salon_settings = SalonSettings.query.first()
    if salon_settings and salon_settings.telegram_bot_token:
        print("🔗 Attempting to set Telegram webhook...")
        
        webhook_url = f"https://hairsalon-1560.onrender.com/telegram-webhook"
        
        try:
            url = f"https://api.telegram.org/bot{salon_settings.telegram_bot_token}/setWebhook"
            response = requests.post(url, json={'url': webhook_url}, timeout=10)
            
            if response.status_code == 200:
                print(f"✅ Telegram webhook set: {webhook_url}")
            else:
                print(f"⚠️  Failed to set webhook: {response.text}")
        except Exception as e:
            print(f"⚠️  Could not set webhook: {e}")
            print("   Note: Telegram cannot reach localhost. Use ngrok for testing.")

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# =========================
# ROUTES
# =========================

@app.route('/')
def index():
    """Home page"""
    referral_code = request.args.get('ref', '')
    
    print(f"DEBUG: TELEGRAM_BOT_LINK = {app.config['TELEGRAM_BOT_LINK']}")
    
    return render_template('index.html', 
                          referral_code=referral_code,
                          TELEGRAM_BOT_LINK=app.config['TELEGRAM_BOT_LINK'])

@app.route('/login')
def login_page():
    """Customer login page"""
    return render_template('login.html',
                          TELEGRAM_BOT_LINK=app.config['TELEGRAM_BOT_LINK'])

@app.route('/customer-login', methods=['POST'])
def customer_login():
    """Process customer login"""
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '').strip()
    
    phone_normalized = normalize_phone_number(phone)
    
    customer = Customer.query.filter_by(phone=phone_normalized).first()
    
    # If not found, try alternative formats
    if not customer:
        if phone_normalized.startswith('+60'):
            phone_alt = '+6' + phone_normalized[3:]  # +60123456789 -> +6123456789
            customer = Customer.query.filter_by(phone=phone_alt).first()
    
    if customer:
        password_hash = str(hash(password))
        if customer.password_hash == password_hash:
            session['customer_id'] = customer.id
            session['customer_name'] = customer.name
            session['customer_points'] = customer.points
            flash(f'Welcome back, {customer.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Incorrect password. Please try again.', 'error')
    else:
        flash('Phone number not found. Please register first.', 'error')
    
    return redirect(url_for('login_page'))

@app.route('/register', methods=['POST'])
def register():
    """Register new customer"""
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    telegram = request.form.get('telegram', '').strip()
    referral_code = request.form.get('referral_code', '').strip()
    
    print(f"DEBUG REGISTER: Raw phone input: '{phone}'")
    
    if not phone:
        flash('Phone number is required', 'error')
        return redirect(url_for('index'))
    
    phone_normalized = normalize_phone_number(phone)
    
    print(f"DEBUG REGISTER: Normalized phone: '{phone_normalized}'")
    
    if not phone_normalized:
        flash('Invalid phone number format. Please enter a valid Malaysian phone number (e.g., 012-3456789 or 0123456789)', 'error')
        return redirect(url_for('index'))
    
    existing = Customer.query.filter_by(phone=phone_normalized).first()
    
    if not existing:
        if phone_normalized.startswith('+60'):
            phone_alt = '+6' + phone_normalized[3:]  # +60123456789 -> +6123456789
            print(f"DEBUG REGISTER: Trying alt format 1: {phone_alt}")
            existing = Customer.query.filter_by(phone=phone_alt).first()
        
        if not existing:
            phone_alt = phone_normalized[1:] if phone_normalized.startswith('+') else phone_normalized
            print(f"DEBUG REGISTER: Trying alt format 2: {phone_alt}")
            existing = Customer.query.filter_by(phone=phone_alt).first()
    
    if existing:
        session['customer_id'] = existing.id
        session['customer_name'] = existing.name
        session['customer_points'] = existing.points
        flash(f'Welcome back {existing.name}! Please login with your password.', 'info')
        return redirect(url_for('login_page'))
    
    customer_referral_code = generate_referral_code()
    password_hash = str(hash(password))
    
    if telegram and telegram.startswith('@'):
        telegram = telegram[1:]
    telegram = telegram.strip() if telegram else None
    
    referrer = None
    if referral_code:
        referrer = Customer.query.filter_by(referral_code=referral_code).first()
    
    customer = Customer(
        name=name,
        phone=phone_normalized,
        telegram_id=telegram,
        points=10,
        referral_code=customer_referral_code,
        referred_by=referrer.id if referrer else None,
        password_hash=password_hash
    )
    
    db.session.add(customer)
    db.session.commit()
    
    if referrer:
        referral = Referral(
            referrer_id=referrer.id,
            referred_id=customer.id,
            referral_code=referral_code,
            status='pending'
        )
        db.session.add(referral)
        db.session.commit()
        
        if referrer.telegram_id:
            send_telegram_to_customer(referrer, 
                f"🎉 New referral! {name} registered using your link.")
    
    salon_settings = SalonSettings.query.first()
    if salon_settings.telegram_chat_id:
        admin_message = f"👤 New Customer Registered!\n\nName: {name}\nPhone: {phone_normalized}\n"
        if telegram:
            admin_message += f"Telegram: @{telegram}\n"
        admin_message += f"Points: 10\nReferral Code: {customer_referral_code}"
        send_telegram_message(salon_settings.telegram_chat_id, admin_message)
    
    session['customer_id'] = customer.id
    session['customer_name'] = customer.name
    session['customer_points'] = customer.points
    
    flash(f'Welcome {name}! You got 10 points.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/forgot-password')
def forgot_password_page():
    """Forgot password page"""
    return render_template('forgot_password.html')

@app.route('/request-password-reset', methods=['POST'])
def request_password_reset():
    """Request password reset"""
    phone = request.form.get('phone', '').strip()
    phone_normalized = normalize_phone_number(phone)
    
    customer = Customer.query.filter_by(phone=phone_normalized).first()
    
    if not customer:
        if phone_normalized.startswith('+60'):
            phone_alt = '+6' + phone_normalized[3:]  # +60123456789 -> +6123456789
            customer = Customer.query.filter_by(phone=phone_alt).first()
    
    if not customer:
        flash('Phone number not found.', 'error')
        return redirect(url_for('forgot_password_page'))
    
    import secrets
    reset_token = secrets.token_urlsafe(32)
    
    customer.reset_token = reset_token
    customer.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()
    
    flash(f'Password reset token: {reset_token}. Please contact admin if you need help.', 'info')
    
    return redirect(url_for('reset_password_page', token=reset_token))

@app.route('/reset-password')
def reset_password_page():
    """Reset password page"""
    token = request.args.get('token', '')
    return render_template('reset_password.html', token=token)

@app.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password"""
    token = request.form.get('token', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    if len(new_password) < 6:
        flash('Password must be at least 6 characters long', 'error')
        return redirect(url_for('reset_password_page', token=token))
    
    if new_password != confirm_password:
        flash('Passwords do not match', 'error')
        return redirect(url_for('reset_password_page', token=token))
    
    customer = Customer.query.filter_by(reset_token=token).first()
    
    if not customer:
        flash('Invalid or expired reset token', 'error')
        return redirect(url_for('forgot_password_page'))
    
    if customer.reset_token_expiry < datetime.utcnow():
        flash('Reset token has expired', 'error')
        return redirect(url_for('forgot_password_page'))
    
    customer.password_hash = str(hash(new_password))
    customer.reset_token = None
    customer.reset_token_expiry = None
    db.session.commit()
    
    flash('Password reset successfully! You can now login with your new password.', 'success')
    return redirect(url_for('login_page'))

@app.route('/admin/reset-customer-password', methods=['POST'])
def admin_reset_customer_password():
    """Admin reset customer password"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    customer_id = request.form.get('customer_id')
    new_password = request.form.get('new_password', '').strip()
    
    if len(new_password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters'})
    
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    customer.password_hash = str(hash(new_password))
    customer.reset_token = None
    customer.reset_token_expiry = None
    db.session.commit()
    
    print(f"Admin reset password for customer: {customer.name} (ID: {customer.id})")
    
    return jsonify({'success': True, 'message': f'Password reset for {customer.name}'})

@app.route('/dashboard')
def dashboard():
    """Customer dashboard"""
    if 'customer_id' not in session:
        return redirect(url_for('index'))
    
    customer_id = session['customer_id']
    customer = db.session.get(Customer, customer_id)
    
    if not customer:
        session.clear()
        return redirect(url_for('index'))
    
    salon_settings = SalonSettings.query.first()
    max_appointments = salon_settings.max_daily_appointments
    
    # Get month from query parameter, default to current month
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    
    today = date.today()
    if year and month:
        # Navigate to specified month
        current_date = date(year, month, 1)
    else:
        current_date = today
    
    # Calculate first day of the month and last day
    if current_date.month == 12:
        next_month = date(current_date.year + 1, 1, 1)
    else:
        next_month = date(current_date.year, current_date.month + 1, 1)
    
    last_day_of_month = next_month - timedelta(days=1)
    
    # Find the first day to display (might include days from previous month)
    first_display_date = current_date.replace(day=1)
    # Adjust to start from Monday (0 = Monday, 6 = Sunday)
    while first_display_date.weekday() != 0:  # 0 = Monday
        first_display_date -= timedelta(days=1)
    
    # Generate 42 days (6 weeks) to ensure full calendar
    calendar_days = []
    for i in range(42):
        day_date = first_display_date + timedelta(days=i)
        
        # Determine if this day is in the current month
        is_current_month = (day_date.month == current_date.month and 
                           day_date.year == current_date.year)
        
        color, status, count = get_date_color(day_date)
        calendar_days.append({
            'date': day_date,
            'day': day_date.day,
            'month': day_date.month,
            'year': day_date.year,
            'day_name': day_date.strftime('%a'),
            'day_num': day_date.weekday(),
            'color': color,
            'status': status,
            'count': count,
            'max': max_appointments,
            'available': count < max_appointments,
            'is_today': day_date == today,
            'is_current_month': is_current_month,
            'is_past': day_date < today and not is_current_month
        })
    
    # Get all active services from database
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    
    successful_referrals = Referral.query.filter_by(
        referrer_id=customer.id,
        status='completed'
    ).count()
    
    pending_referrals = Referral.query.filter_by(
        referrer_id=customer.id,
        status='pending'
    ).count()
    
    referral_url = f"{request.host_url}?ref={customer.referral_code}"
    
    customer_appointments = Appointment.query.filter_by(
        customer_id=customer.id
    ).order_by(Appointment.appointment_time.desc()).all()
    
    # Calculate previous and next month for navigation
    if current_date.month == 1:
        prev_month = date(current_date.year - 1, 12, 1)
    else:
        prev_month = date(current_date.year, current_date.month - 1, 1)
    
    if current_date.month == 12:
        next_month = date(current_date.year + 1, 1, 1)
    else:
        next_month = date(current_date.year, current_date.month + 1, 1)
    
    return render_template('dashboard.html',
        customer=customer,
        calendar_days=calendar_days,
        services=services,
        successful_referrals=successful_referrals,
        pending_referrals=pending_referrals,
        referral_url=referral_url,
        appointments=customer_appointments[:5],
        TELEGRAM_BOT_LINK=app.config['TELEGRAM_BOT_LINK'],
        current_month=current_date.strftime('%B %Y'),
        current_year=current_date.year,
        current_month_num=current_date.month,
        prev_month=prev_month,
        next_month=next_month
    )

@app.route('/api/time-slots')
def api_time_slots():
    """Get available time slots for date (legacy)"""
    date_str = request.args.get('date')
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return jsonify({'error': 'Invalid date'})
    
    salon_settings = SalonSettings.query.first()
    if salon_settings:
        print(f"DEBUG: Working hours - Start: {salon_settings.working_hours_start}, End: {salon_settings.working_hours_end}")
        print(f"DEBUG: Appointment duration: {salon_settings.appointment_duration} minutes")
    
    time_slots = get_available_time_slots(date_obj)
    
    return jsonify({
        'date': date_str,
        'time_slots': [{
            'time': slot['time'],
            'datetime': slot['datetime'].isoformat()
        } for slot in time_slots]
    })

@app.route('/api/service-time-slots')
def api_service_time_slots():
    """Get available time slots for a specific service"""
    date_str = request.args.get('date')
    service_id = request.args.get('service_id')
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return jsonify({'error': 'Invalid date'})
    
    if service_id:
        service = db.session.get(Service, service_id)
        if not service:
            return jsonify({'error': 'Service not found'})
        duration = service.duration
        service_name = service.name
    else:
        # Default to salon setting if no service specified
        salon_settings = SalonSettings.query.first()
        duration = salon_settings.appointment_duration if salon_settings else 60
        service_name = 'Default'
    
    time_slots = get_available_time_slots(date_obj, duration)
    
    return jsonify({
        'date': date_str,
        'duration': duration,
        'service_name': service_name,
        'time_slots': [{
            'time': slot['time'],
            'datetime': slot['datetime'].isoformat(),
            'end_time': slot['end_time']
        } for slot in time_slots]
    })

@app.route('/api/check-points')
def api_check_points():
    """Check customer points"""
    if 'customer_id' not in session:
        return jsonify({'points': 0})
    
    customer_id = session['customer_id']
    customer = db.session.get(Customer, customer_id)
    
    return jsonify({
        'points': customer.points if customer else 0
    })

@app.route('/change-password', methods=['POST'])
def change_password():
    """Change customer password from dashboard"""
    if 'customer_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    customer_id = session['customer_id']
    customer = db.session.get(Customer, customer_id)
    
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    data = request.get_json()
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    
    # Validate current password
    current_hash = str(hash(current_password))
    if customer.password_hash != current_hash:
        return jsonify({'success': False, 'error': 'Current password is incorrect'})
    
    # Validate new password
    if len(new_password) < 6:
        return jsonify({'success': False, 'error': 'New password must be at least 6 characters'})
    
    # Update password
    customer.password_hash = str(hash(new_password))
    db.session.commit()
    
    # Send Telegram notification if connected
    if customer.telegram_chat_id:
        try:
            message = f"🔐 Your password has been changed successfully.\n"
            message += f"If you didn't make this change, please contact the salon immediately!"
            send_telegram_message(customer.telegram_chat_id, message)
        except Exception as e:
            print(f"Failed to send Telegram notification: {e}")
    
    print(f"Password changed for customer: {customer.name} (ID: {customer.id})")
    
    return jsonify({
        'success': True,
        'message': 'Password updated successfully!'
    })

@app.route('/api/services')
def api_get_services():
    """Get all active services"""
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    
    return jsonify({
        'services': [service.to_dict() for service in services]
    })

@app.route('/book-appointment', methods=['POST'])
def book_appointment():
    """Book appointment"""
    if 'customer_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    customer_id = session['customer_id']
    customer = db.session.get(Customer, customer_id)
    
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    if customer.points < 10:
        return jsonify({'success': False, 'error': 'Not enough points'})
    
    date_str = request.form.get('date')
    time_str = request.form.get('time')
    service_id = request.form.get('service_id')
    service_name = request.form.get('service_name')
    
    # DEBUG: Print received values
    print(f"DEBUG BOOKING: service_id={service_id}, service_name={service_name}")
    
    try:
        appointment_time = datetime.fromisoformat(time_str)
    except:
        return jsonify({'success': False, 'error': 'Invalid time format'})
    
    # Get service duration and ensure we have a service name
    service = None
    duration = None
    final_service_name = None
    
    # Try to get service by ID first
    if service_id and service_id.isdigit():
        service = db.session.get(Service, int(service_id))
        if service:
            duration = service.duration
            final_service_name = service.name
            print(f"DEBUG: Found service by ID: {service.name}")
    
    # If no service found by ID but we have service_name from form
    if not service and service_name:
        final_service_name = service_name
        print(f"DEBUG: Using service_name from form: {service_name}")
        
        # Try to find service by name
        service = Service.query.filter_by(name=service_name).first()
        if service:
            duration = service.duration
            print(f"DEBUG: Found service by name: {service.name}")
    
    # If still no duration, use default
    if not duration:
        salon_settings = SalonSettings.query.first()
        duration = salon_settings.appointment_duration
        print(f"DEBUG: Using default duration: {duration}")
    
    # If still no service name, use a default
    if not final_service_name:
        final_service_name = "Hair Service"
        print(f"DEBUG: Using default service name: {final_service_name}")
    
    # Check if slot is available with this duration
    date_obj = appointment_time.date()
    available_slots = get_available_time_slots(date_obj, duration)
    slot_available = any(
        slot['datetime'] == appointment_time 
        for slot in available_slots
    )
    
    if not slot_available:
        return jsonify({'success': False, 'error': 'Time slot no longer available for this service duration'})
    
    salon_settings = SalonSettings.query.first()
    appointment_count = Appointment.query.filter(
        db.func.date(Appointment.appointment_time) == date_obj,
        Appointment.status.in_(['pending', 'confirmed'])
    ).count()
    
    if appointment_count >= salon_settings.max_daily_appointments:
        return jsonify({'success': False, 'error': 'Date is fully booked'})
    
    # Calculate end time
    end_time = appointment_time + timedelta(minutes=duration)
    
    # Deduct points
    old_points = customer.points
    customer.points -= 10
    
    # Create appointment with all required fields
    appointment = Appointment(
        customer_id=customer.id,
        service_id=service.id if service else None,
        service_type=final_service_name,  # This must NOT be None
        appointment_time=appointment_time,
        duration=duration,
        end_time=end_time,
        points_deducted=10,
        status='confirmed'
    )
    
    # DEBUG: Print appointment details before commit
    print(f"DEBUG: Creating appointment with service_type: {appointment.service_type}")
    
    try:
        db.session.add(appointment)
        
        # Add points history
        points_history = PointsHistory(
            customer_id=customer.id,
            old_points=old_points,
            new_points=customer.points,
            difference=-10,
            reason=f'Appointment booking: {final_service_name}',
            changed_by='system'
        )
        db.session.add(points_history)
        
        db.session.commit()
        
        session['customer_points'] = customer.points
        
        # Send confirmation
        send_appointment_confirmation(customer, appointment)
        
        return jsonify({
            'success': True, 
            'message': f'Appointment booked! Duration: {duration} minutes',
            'end_time': end_time.strftime('%I:%M %p')
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"ERROR booking appointment: {str(e)}")
        return jsonify({
            'success': False, 
            'error': f'Database error: {str(e)}'
        })

# =========================
# APPOINTMENT CANCELLATION ROUTES
# =========================

@app.route('/cancel-appointment', methods=['POST'])
def cancel_appointment():
    """Customer cancel appointment"""
    if 'customer_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    customer_id = session['customer_id']
    customer = db.session.get(Customer, customer_id)
    
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    try:
        data = request.get_json()
        appointment_id = data.get('appointment_id')
    except:
        return jsonify({'success': False, 'error': 'Invalid request'})
    
    appointment = db.session.get(Appointment, appointment_id)
    
    if not appointment:
        return jsonify({'success': False, 'error': 'Appointment not found'})
    
    if appointment.customer_id != customer.id:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    if appointment.status not in ['pending', 'confirmed']:
        return jsonify({'success': False, 'error': 'Appointment cannot be cancelled'})
    
    try:
        current_time = datetime.utcnow()
        appointment_time = appointment.appointment_time
        time_diff = (appointment_time - current_time).total_seconds() / 3600  # hours
        
        # Determine points refund based on cancellation time
        if time_diff < 2:
            # Within 2 hours - deduct 5 points (refund 5 points)
            points_to_refund = 5
            message = "Appointment cancelled within 2 hours. 5 points deducted (only 5 points refunded)."
        else:
            # More than 2 hours before - full refund
            points_to_refund = 10
            message = "Appointment cancelled. 10 points refunded."
        
        old_points = customer.points
        
        customer.points += points_to_refund
        
        appointment.status = 'cancelled'
        appointment.cancelled_at = current_time
        
        points_history = PointsHistory(
            customer_id=customer.id,
            old_points=old_points,
            new_points=customer.points,
            difference=points_to_refund,
            reason=f'Appointment cancellation refund: {appointment.service_type}',
            changed_by='system'
        )
        db.session.add(points_history)
        
        db.session.commit()
        
        session['customer_points'] = customer.points
        
        if customer.telegram_id:
            telegram_message = f"❌ Appointment Cancelled\n\n"
            telegram_message += f"Service: {appointment.service_type}\n"
            telegram_message += f"Date: {appointment.appointment_time.strftime('%Y-%m-%d')}\n"
            telegram_message += f"Time: {appointment.appointment_time.strftime('%I:%M %p')}\n"
            telegram_message += f"Refunded: {points_to_refund} points\n"
            telegram_message += f"New points balance: {customer.points}"
            send_telegram_to_customer(customer, telegram_message)
        
        salon_settings = SalonSettings.query.first()
        if salon_settings and salon_settings.telegram_chat_id:
            admin_message = f"❌ Appointment Cancelled\n\n"
            admin_message += f"Customer: {customer.name}\n"
            admin_message += f"Phone: {customer.phone}\n"
            admin_message += f"Service: {appointment.service_type}\n"
            admin_message += f"Time: {appointment.appointment_time.strftime('%Y-%m-%d %I:%M %p')}\n"
            admin_message += f"Cancelled at: {current_time.strftime('%Y-%m-%d %I:%M %p')}\n"
            admin_message += f"Hours before appointment: {time_diff:.1f}h\n"
            admin_message += f"Points refunded: {points_to_refund}"
            send_telegram_message(salon_settings.telegram_chat_id, admin_message)
        
        return jsonify({
            'success': True, 
            'message': message,
            'points_refunded': points_to_refund,
            'new_points': customer.points
        })
        
    except Exception as e:
        print(f"Error cancelling appointment: {e}")
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Error: {str(e)}'
        })

@app.route('/admin/cancel-appointment', methods=['POST'])
def admin_cancel_appointment():
    """Admin cancel appointment"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    appointment_id = request.form.get('appointment_id')
    reason = request.form.get('reason', '').strip()
    
    appointment = db.session.get(Appointment, appointment_id)
    
    if not appointment:
        return jsonify({'success': False, 'error': 'Appointment not found'})
    
    customer = db.session.get(Customer, appointment.customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    try:
        old_points = customer.points
        points_to_refund = 10
        
        customer.points += points_to_refund
        
        appointment.status = 'cancelled'
        appointment.cancelled_at = datetime.utcnow()
        appointment.admin_cancelled = True
        appointment.cancellation_reason = reason if reason else 'Cancelled by admin'
        
        points_history = PointsHistory(
            customer_id=customer.id,
            old_points=old_points,
            new_points=customer.points,
            difference=points_to_refund,
            reason=f'Admin appointment cancellation: {appointment.service_type}' + 
                  (f' - {reason}' if reason else ''),
            changed_by='admin'
        )
        db.session.add(points_history)
        
        db.session.commit()
        
        if customer.telegram_id:
            telegram_message = f"❌ Appointment Cancelled by Admin\n\n"
            telegram_message += f"Service: {appointment.service_type}\n"
            telegram_message += f"Date: {appointment.appointment_time.strftime('%Y-%m-%d')}\n"
            telegram_message += f"Time: {appointment.appointment_time.strftime('%I:%M %p')}\n"
            telegram_message += f"Refunded: {points_to_refund} points\n"
            if reason:
                telegram_message += f"Reason: {reason}\n"
            telegram_message += f"New points balance: {customer.points}"
            send_telegram_to_customer(customer, telegram_message)
        
        return jsonify({
            'success': True, 
            'message': f'Appointment cancelled. Refunded {points_to_refund} points to {customer.name}',
            'customer_name': customer.name,
            'appointment_id': appointment_id
        })
        
    except Exception as e:
        print(f"Error cancelling appointment: {e}")
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Error: {str(e)}'
        })

@app.route('/complete-appointment', methods=['POST'])
def complete_appointment():
    """Complete appointment and award points (admin only)"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    appointment_id = request.form.get('appointment_id')
    appointment = db.session.get(Appointment, appointment_id)
    
    if not appointment:
        return jsonify({'success': False, 'error': 'Appointment not found'})
    
    customer = db.session.get(Customer, appointment.customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    try:
        old_points = customer.points
        
        appointment.status = 'completed'
        customer.points += 20
        
        points_history = PointsHistory(
            customer_id=customer.id,
            old_points=old_points,
            new_points=customer.points,
            difference=20,
            reason=f'Appointment completion: {appointment.service_type}',
            changed_by='system'
        )
        db.session.add(points_history)
        
        db.session.commit()
        
        referral_awarded = award_referral_points(customer.id)
        
        if referral_awarded:
            referral_points_history = PointsHistory(
                customer_id=customer.referred_by,
                old_points=Customer.query.get(customer.referred_by).points - 10,
                new_points=Customer.query.get(customer.referred_by).points,
                difference=10,
                reason=f'Referral bonus for {customer.name}',
                changed_by='system'
            )
            db.session.add(referral_points_history)
        
        db.session.commit()
        
        if customer.telegram_id:
            message = f"✅ Your appointment for {appointment.service_type} has been completed! You've earned 20 points."
            send_telegram_to_customer(customer, message)
        
        success_msg = f"Appointment completed for {customer.name}! Awarded 20 points."
        if referral_awarded:
            success_msg += " Referral bonus awarded!"
        
        return jsonify({
            'success': True, 
            'message': success_msg,
            'customer_name': customer.name,
            'appointment_id': appointment_id
        })
        
    except Exception as e:
        print(f"Error completing appointment: {e}")
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Error: {str(e)}'
        })

@app.route('/admin-login')
def admin_login_page():
    """Admin login page"""
    return render_template('admin_login.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """Process admin login"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'admin123'
    
    if (username == ADMIN_USERNAME and password == ADMIN_PASSWORD):
        session['admin_logged_in'] = True
        return redirect(url_for('admin_dashboard'))
    
    flash('Invalid admin credentials', 'error')
    return redirect(url_for('admin_login_page'))

@app.route('/admin/dashboard')
def admin_dashboard():
    """Admin dashboard"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    salon_settings = SalonSettings.query.first()
    
    # Now these ORM queries should work since the database has been migrated
    total_customers = Customer.query.count()
    total_appointments = Appointment.query.count()
    pending_appointments = Appointment.query.filter_by(status='pending').count()
    total_services = Service.query.count()
    active_services = Service.query.filter_by(is_active=True).count()
    
    today = date.today()
    today_appointments = Appointment.query.filter(
        db.func.date(Appointment.appointment_time) == today
    ).count()
    
    # Get recent appointments with customer info
    recent_appointments = Appointment.query.options(
        db.joinedload(Appointment.customer)
    ).order_by(
        Appointment.appointment_time.desc()
    ).limit(10).all()
    
    # Get today's upcoming appointments
    upcoming_today = Appointment.query.options(
        db.joinedload(Appointment.customer)
    ).filter(
        db.func.date(Appointment.appointment_time) == today,
        Appointment.status.in_(['pending', 'confirmed'])
    ).order_by(Appointment.appointment_time).all()
    
    return render_template('admin_dashboard.html',
        salon_settings=salon_settings,
        total_customers=total_customers,
        total_appointments=total_appointments,
        pending_appointments=pending_appointments,
        today_appointments=today_appointments,
        recent_appointments=recent_appointments,
        upcoming_today=upcoming_today,
        total_services=total_services,
        active_services=active_services
    )

@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    """Admin settings page"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    salon_settings = SalonSettings.query.first()
    
    if request.method == 'POST':
        salon_settings.business_name = request.form.get('business_name', '').strip()
        salon_settings.max_daily_appointments = int(request.form.get('max_daily_appointments', 10))
        salon_settings.appointment_duration = int(request.form.get('appointment_duration', 60))
        salon_settings.working_hours_start = request.form.get('working_hours_start', '09:00')
        salon_settings.working_hours_end = request.form.get('working_hours_end', '18:00')
        salon_settings.telegram_chat_id = request.form.get('telegram_chat_id', '').strip()
        salon_settings.telegram_bot_token = request.form.get('telegram_bot_token', '').strip()
        
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('admin_settings'))
    
    return render_template('admin_settings.html', salon_settings=salon_settings)

@app.route('/admin/appointments')
def admin_appointments():
    """Admin appointments management"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    status_filter = request.args.get('status', 'all')
    date_filter = request.args.get('date', '')
    
    query = Appointment.query.options(db.joinedload(Appointment.customer))
    
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    if date_filter:
        try:
            date_obj = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Appointment.appointment_time) == date_obj)
        except:
            pass
    
    appointments = query.order_by(Appointment.appointment_time.desc()).all()
    
    return render_template('admin_appointments.html', 
        appointments=appointments,
        status_filter=status_filter,
        date_filter=date_filter
    )

@app.route('/admin/customers')
def admin_customers():
    """Admin customers management"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    
    recent_customers = customers[:5]
    top_customers = sorted(customers, key=lambda c: c.points, reverse=True)[:5]
    
    low_points = len([c for c in customers if c.points <= 49])
    medium_points = len([c for c in customers if 50 <= c.points <= 99])
    high_points = len([c for c in customers if c.points >= 100])
    
    return render_template('admin_customers.html', 
        customers=customers,
        recent_customers=recent_customers,
        top_customers=top_customers,
        low_points=low_points,
        medium_points=medium_points,
        high_points=high_points
    )

# =========================
# SERVICE MANAGEMENT ROUTES
# =========================

@app.route('/admin/services')
def admin_services():
    """Admin services management"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    services = Service.query.order_by(Service.name).all()
    
    return render_template('admin_services.html', services=services)

@app.route('/admin/services/add', methods=['POST'])
def admin_add_service():
    """Add new service"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    name = request.form.get('name', '').strip()
    duration = request.form.get('duration', 0)
    description = request.form.get('description', '').strip()
    price = request.form.get('price', '').strip()
    
    if not name:
        return jsonify({'success': False, 'error': 'Service name is required'})
    
    try:
        duration = int(duration)
        if duration < 15 or duration > 480:
            return jsonify({'success': False, 'error': 'Duration must be between 15 and 480 minutes'})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid duration'})
    
    # Parse price if provided
    price_float = None
    if price:
        try:
            price_float = float(price)
        except ValueError:
            pass
    
    service = Service(
        name=name,
        duration=duration,
        description=description,
        price=price_float
    )
    
    db.session.add(service)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Service "{name}" added successfully',
        'service': service.to_dict()
    })

@app.route('/admin/services/update', methods=['POST'])
def admin_update_service():
    """Update existing service"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    service_id = request.form.get('service_id')
    name = request.form.get('name', '').strip()
    duration = request.form.get('duration', 0)
    description = request.form.get('description', '').strip()
    price = request.form.get('price', '').strip()
    is_active = request.form.get('is_active') == 'on'
    
    service = db.session.get(Service, service_id)
    if not service:
        return jsonify({'success': False, 'error': 'Service not found'})
    
    if not name:
        return jsonify({'success': False, 'error': 'Service name is required'})
    
    try:
        duration = int(duration)
        if duration < 15 or duration > 480:
            return jsonify({'success': False, 'error': 'Duration must be between 15 and 480 minutes'})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid duration'})
    
    # Parse price if provided
    price_float = None
    if price:
        try:
            price_float = float(price)
        except ValueError:
            pass
    
    service.name = name
    service.duration = duration
    service.description = description
    service.price = price_float
    service.is_active = is_active
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Service "{name}" updated successfully',
        'service': service.to_dict()
    })

@app.route('/admin/services/delete/<int:service_id>', methods=['POST'])
def admin_delete_service(service_id):
    """Delete service"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    service = db.session.get(Service, service_id)
    if not service:
        return jsonify({'success': False, 'error': 'Service not found'})
    
    # Check if service has appointments
    appointment_count = Appointment.query.filter_by(service_id=service.id).count()
    if appointment_count > 0:
        # Instead of deleting, just deactivate
        service.is_active = False
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Service "{service.name}" deactivated (has {appointment_count} appointments)'
        })
    
    db.session.delete(service)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Service "{service.name}" deleted successfully'
    })

# =========================
# END SERVICE MANAGEMENT
# =========================

@app.route('/logout')
def logout():
    """Logout customer"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/logout')
def admin_logout():
    """Logout admin"""
    session.clear()
    return redirect(url_for('admin_login_page'))

@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    """Handle Telegram webhook"""
    try:
        data = request.get_json()
        print(f"Telegram webhook received: {json.dumps(data, indent=2)}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').strip()
            
            if message['chat']['type'] == 'private':
                telegram_chat = TelegramChat.query.filter_by(chat_id=str(chat_id)).first()
                
                if not telegram_chat:
                    first_name = message['chat'].get('first_name', '')
                    last_name = message['chat'].get('last_name', '')
                    username = message['chat'].get('username', '')
                    
                    telegram_chat = TelegramChat(
                        chat_id=str(chat_id),
                        first_name=first_name,
                        last_name=last_name,
                        username=username,
                        chat_type='private'
                    )
                    db.session.add(telegram_chat)
                    db.session.commit()
                    
                    salon_settings = SalonSettings.query.first()
                    if salon_settings and not salon_settings.telegram_chat_id:
                        salon_settings.telegram_chat_id = str(chat_id)
                        db.session.commit()
                        welcome_msg = "👋 Welcome! You are now connected as the admin chat."
                    else:
                        welcome_msg = f"👋 Welcome {first_name}! You'll receive appointment notifications here."
                    
                    send_telegram_message(chat_id, welcome_msg)
                
                if text == '/start':
                    first_name = message['chat'].get('first_name', 'there')
                    
                    welcome_message = f"""👋 Hello {first_name}!

Welcome to *HS Salon Bot* 🤖

I'll help you with:
• 📅 Appointment confirmations
• ⏰ Appointment reminders
• ⭐ Points updates
• 📢 Referral notifications

To link your account, use:
/link [your-phone-number]
Example: /link +60123456789

Use /help to see all commands.

Happy styling! ✂️"""
                    
                    send_telegram_message(chat_id, welcome_message)
                    
                    username = message['chat'].get('username', '')
                    if username:
                        customer = Customer.query.filter_by(telegram_id=username).first()
                        if customer:
                            customer.telegram_chat_id = str(chat_id)
                            db.session.commit()
                            send_telegram_message(chat_id, f"✅ Your Telegram is now linked to your account: {customer.name}")
                
                elif text == '/help':
                    help_message = """🤖 <b>HS Salon Bot Commands</b>

/start - Start the bot and get welcome message
/help - Show this help message
/link [phone] - Link your Telegram to your account
Example: /link +60123456789

You'll automatically receive:
• Appointment confirmations
• Appointment reminders
• Points updates
• Referral notifications"""
                    send_telegram_message(chat_id, help_message)
                
                elif text.startswith('/link'):
                    parts = text.split()
                    if len(parts) > 1:
                        phone = parts[1]
                        phone_normalized = normalize_phone_number(phone)
        
                        customer = Customer.query.filter_by(phone=phone_normalized).first()
        
                        if not customer:
                            if phone_normalized.startswith('+60'):
                                phone_alt = '+6' + phone_normalized[3:]
                                customer = Customer.query.filter_by(phone=phone_alt).first()
                        
                        if customer:
                            username = message['chat'].get('username', '')
                            if username:
                                customer.telegram_id = username
                                customer.telegram_chat_id = str(chat_id)
                                db.session.commit()
                                
                                send_telegram_message(chat_id, f"✅ Successfully linked Telegram to your account: {customer.name}")
                                send_telegram_message(chat_id, f"📱 Phone: {customer.phone}")
                                send_telegram_message(chat_id, f"⭐ Points: {customer.points}")
                            else:
                                send_telegram_message(chat_id, "❌ Please set a username in Telegram first.")
                        else:
                            send_telegram_message(chat_id, "❌ Customer not found. Please check your phone number.")
                    else:
                        send_telegram_message(chat_id, "Usage: /link [phone]\nExample: /link +60123456789")
        
        return jsonify({'success': True})
    
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/set-webhook')
def set_webhook():
    """Set Telegram webhook URL"""
    salon_settings = SalonSettings.query.first()
    
    if not salon_settings or not salon_settings.telegram_bot_token:
        return """
        <h3>❌ No Telegram Bot Token Configured</h3>
        <p>Please set your Telegram bot token in:</p>
        <ol>
            <li>Admin Panel → Settings → Telegram Bot Token</li>
            <li>OR in config.py as TELEGRAM_BOT_TOKEN</li>
        </ol>
        <p><a href="/admin/settings">Go to Admin Settings</a></p>
        """
    
    bot_token = salon_settings.telegram_bot_token
    
    webhook_url = f"{request.host_url}telegram-webhook"
    
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        'url': webhook_url
    }
    
    try:
        import requests
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Telegram Webhook Setup</title>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 20px; }}
                    .success {{ color: green; }}
                    .info {{ background: #e8f4fc; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                </style>
            </head>
            <body>
                <h2 class="success">✅ Telegram Webhook Set Successfully!</h2>
                
                <div class="info">
                    <p><strong>Bot Token:</strong> {bot_token[:10]}...{bot_token[-10:] if len(bot_token) > 20 else ''}</p>
                    <p><strong>Webhook URL:</strong> {webhook_url}</p>
                </div>
                
                <h3>Webhook Info:</h3>
                <pre>{json.dumps(result, indent=2)}</pre>
                
                <p><a href="/telegram-webhook-status">Check Webhook Status</a></p>
                <p><a href="/admin/settings">Back to Settings</a></p>
            </body>
            </html>
            """
        else:
            return f"""
            <h3>❌ Failed to Set Webhook</h3>
            <p>Error: {response.text}</p>
            <p>URL attempted: {url}</p>
            <p>Webhook URL: {webhook_url}</p>
            """
            
    except Exception as e:
        return f"""
        <h3>❌ Error Setting Webhook</h3>
        <p>Exception: {str(e)}</p>
        <p>Make sure you have a valid Telegram bot token and internet connection.</p>
        """

@app.route('/telegram-webhook-status')
def telegram_webhook_status():
    """Check Telegram webhook status"""
    salon_settings = SalonSettings.query.first()
    
    if not salon_settings or not salon_settings.telegram_bot_token:
        return """
        <h3>❌ No Telegram Bot Token Configured</h3>
        <p>Please set your Telegram bot token first.</p>
        <p><a href="/admin/settings">Go to Admin Settings</a></p>
        """
    
    bot_token = salon_settings.telegram_bot_token
    
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            webhook_info = response.json()
            
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Telegram Webhook Status</title>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 20px; }}
                    .success {{ color: green; }}
                    .warning {{ color: orange; }}
                    .error {{ color: red; }}
                    .info {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                    pre {{ background: #f5f5f5; padding: 15px; border-radius: 5px; overflow: auto; }}
                </style>
            </head>
            <body>
                <h2>📡 Telegram Webhook Status</h2>
                
                <div class="info">
                    <p><strong>Your local webhook URL should be:</strong></p>
                    <p><code>{request.host_url}telegram-webhook</code></p>
                    <p><em>Note: Telegram cannot reach localhost. Use ngrok for testing.</em></p>
                </div>
                
                <h3>Current Webhook Information:</h3>
                <pre>{json.dumps(webhook_info, indent=2)}</pre>
                
                <p><a href="/set-webhook">Set Webhook</a> | 
                <a href="/admin/settings">Settings</a> | 
                <a href="/">Home</a></p>
            </body>
            </html>
            """
        else:
            return f"""
            <h3>❌ Failed to Get Webhook Info</h3>
            <p>Error: {response.text}</p>
            <p>Make sure your bot token is correct.</p>
            """
            
    except Exception as e:
        return f"""
        <h3>❌ Error Checking Webhook</h3>
        <p>Exception: {str(e)}</p>
        """

@app.route('/test-telegram-start')
def test_telegram_start():
    """Test /start command without Telegram"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Telegram /start</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            .container { max-width: 600px; margin: 0 auto; }
            .test-box { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
            button:hover { background: #0056b3; }
            #result { margin-top: 20px; padding: 15px; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Test Telegram /start Command</h1>
            
            <div class="test-box">
                <h3>Simulate /start Command</h3>
                <p>This will simulate a user sending <code>/start</code> to your bot.</p>
                
                <div>
                    <label>Chat ID: </label>
                    <input type="text" id="chatId" value="123456789" style="padding: 8px; width: 200px;">
                </div>
                
                <div style="margin-top: 10px;">
                    <label>Username: </label>
                    <input type="text" id="username" value="testuser" style="padding: 8px; width: 200px;">
                </div>
                
                <button onclick="testStart()" style="margin-top: 15px;">
                    Simulate /start Command
                </button>
                
                <div id="result"></div>
            </div>
            
            <div class="test-box">
                <h3>Quick Links:</h3>
                <ul>
                    <li><a href="/set-webhook">Set Webhook</a></li>
                    <li><a href="/telegram-webhook-status">Check Webhook Status</a></li>
                    <li><a href="/admin/settings">Admin Settings</a></li>
                </ul>
            </div>
        </div>
        
        <script>
        function testStart() {
            const chatId = document.getElementById('chatId').value || '123456789';
            const username = document.getElementById('username').value || 'testuser';
            
            const payload = {
                "update_id": 999999999,
                "message": {
                    "message_id": 1,
                    "from": {
                        "id": parseInt(chatId),
                        "is_bot": false,
                        "first_name": "Test",
                        "last_name": "User",
                        "username": username,
                        "language_code": "en"
                    },
                    "chat": {
                        "id": parseInt(chatId),
                        "first_name": "Test",
                        "last_name": "User",
                        "username": username,
                        "type": "private"
                    },
                    "date": Math.floor(Date.now() / 1000),
                    "text": "/start"
                }
            };
            
            document.getElementById('result').innerHTML = '<p>Sending test...</p>';
            
            fetch('/telegram-webhook', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('result').innerHTML = `
                    <div style="background: #d4edda; padding: 15px; border-radius: 4px;">
                        <h4>✅ Test Sent Successfully!</h4>
                        <p>Response: ${JSON.stringify(data)}</p>
                        <p><strong>Check your Flask console for detailed logs!</strong></p>
                    </div>
                `;
                console.log('Test response:', data);
            })
            .catch(error => {
                document.getElementById('result').innerHTML = `
                    <div style="background: #f8d7da; padding: 15px; border-radius: 4px;">
                        <h4>❌ Error</h4>
                        <p>${error}</p>
                    </div>
                `;
            });
        }
        </script>
    </body>
    </html>
    """

@app.route('/api/telegram-chats')
def api_telegram_chats():
    """Get registered Telegram chats"""
    if 'admin_logged_in' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    chats = TelegramChat.query.all()
    
    return jsonify({
        'chats': [{
            'id': chat.id,
            'chat_id': chat.chat_id,
            'first_name': chat.first_name,
            'last_name': chat.last_name,
            'username': chat.username,
            'chat_type': chat.chat_type,
            'registered_at': chat.registered_at.isoformat() if chat.registered_at else None
        } for chat in chats]
    })

@app.route('/admin/update-customer-points', methods=['POST'])
def admin_update_customer_points():
    """Update customer points"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    customer_id = request.form.get('customer_id')
    new_points = request.form.get('new_points')
    reason = request.form.get('reason', '').strip()
    
    try:
        new_points = int(new_points)
        if new_points < 0:
            return jsonify({'success': False, 'error': 'Points cannot be negative'})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid points value'})
    
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'})
    
    old_points = customer.points
    difference = new_points - old_points
    
    customer.points = new_points
    
    points_history = PointsHistory(
        customer_id=customer.id,
        old_points=old_points,
        new_points=new_points,
        difference=difference,
        reason=reason if reason else 'Admin adjustment',
        changed_by='admin'
    )
    db.session.add(points_history)
    db.session.commit()
    
    print(f"Admin updated points for customer: {customer.name} (ID: {customer.id})")
    print(f"  Old points: {old_points}, New points: {new_points}, Difference: {difference}")
    print(f"  Reason: {reason if reason else 'No reason provided'}")
    
    if customer.telegram_chat_id:
        try:
            message = f"📊 Your points have been updated!\n"
            message += f"Previous: {old_points} points\n"
            message += f"Current: {new_points} points\n"
            if difference != 0:
                message += f"Change: {'+' if difference > 0 else ''}{difference} points\n"
            if reason:
                message += f"Reason: {reason}\n"
            message += f"Thank you for being our valued customer! 💝"
            
            send_telegram_message(customer.telegram_chat_id, message)
        except Exception as e:
            print(f"Failed to send Telegram notification: {e}")
    
    return jsonify({
        'success': True, 
        'message': f'Updated points for {customer.name} from {old_points} to {new_points}'
    })

@app.route('/admin/points-history/<int:customer_id>')
def admin_points_history(customer_id):
    """View points history for a customer"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash('Customer not found', 'error')
        return redirect(url_for('admin_customers'))
    
    history = PointsHistory.query.filter_by(customer_id=customer_id)\
        .order_by(PointsHistory.created_at.desc())\
        .all()
    
    return render_template('admin_points_history.html',
        customer=customer,
        history=history
    )

@app.route('/test-phone', methods=['GET', 'POST'])
def test_phone():
    """Test phone number normalization"""
    if request.method == 'POST':
        phone = request.form.get('phone', '')
        normalized = normalize_phone_number(phone)
        
        return f"""
        <html>
        <body>
            <h2>Phone Number Test</h2>
            <p>Original: {phone}</p>
            <p>Normalized: {normalized}</p>
            <p>Is valid: {normalized is not None}</p>
            <br>
            <form method="post">
                <input type="text" name="phone" placeholder="Enter phone number" value="{phone}">
                <button type="submit">Test</button>
            </form>
            <br>
            <h3>Test Cases:</h3>
            <ul>
                <li>0123456789</li>
                <li>012-345-6789</li>
                <li>012 345 6789</li>
                <li>+60123456789</li>
                <li>60123456789</li>
                <li>123456789</li>
                <li>+6123456789</li>
            </ul>
        </body>
        </html>
        """
    
    return '''
    <html>
    <body>
        <h2>Test Phone Number Normalization</h2>
        <form method="post">
            <input type="text" name="phone" placeholder="Enter phone number">
            <button type="submit">Test</button>
        </form>
    </body>
    </html>
    '''

@app.route('/admin/off-days', methods=['GET', 'POST'])
def admin_off_days():
    """Manage off days"""
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login_page'))
    
    salon_settings = SalonSettings.query.first()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_weekly':
            day_of_week = int(request.form.get('day_of_week'))
            description = request.form.get('description', '').strip()
            
            # Check if already exists
            existing = OffDay.query.filter_by(
                salon_settings_id=salon_settings.id,
                type='weekly',
                day_of_week=day_of_week
            ).first()
            
            if not existing:
                off_day = OffDay(
                    salon_settings_id=salon_settings.id,
                    type='weekly',
                    day_of_week=day_of_week,
                    description=description
                )
                db.session.add(off_day)
                db.session.commit()
                flash(f'Weekly off day added for {["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][day_of_week]}!', 'success')
            else:
                flash('This day is already marked as a weekly off day', 'warning')
        
        elif action == 'add_specific':
            date_str = request.form.get('specific_date')
            description = request.form.get('description', '').strip()
            
            try:
                specific_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                # Check if date is in the past
                if specific_date < date.today():
                    flash('Cannot add off days for past dates', 'error')
                    return redirect(url_for('admin_off_days'))
                
                # Check if already exists
                existing = OffDay.query.filter_by(
                    salon_settings_id=salon_settings.id,
                    type='specific',
                    specific_date=specific_date
                ).first()
                
                if not existing:
                    off_day = OffDay(
                        salon_settings_id=salon_settings.id,
                        type='specific',
                        specific_date=specific_date,
                        description=description
                    )
                    db.session.add(off_day)
                    db.session.commit()
                    flash(f'Specific off day added for {specific_date.strftime("%B %d, %Y")}!', 'success')
                else:
                    flash('This date is already marked as an off day', 'warning')
                    
            except ValueError:
                flash('Invalid date format', 'error')
        
        elif action == 'delete':
            off_day_id = request.form.get('off_day_id')
            off_day = db.session.get(OffDay, off_day_id)
            
            if off_day and off_day.salon_settings_id == salon_settings.id:
                db.session.delete(off_day)
                db.session.commit()
                flash('Off day removed successfully!', 'success')
            else:
                flash('Off day not found', 'error')
        
        return redirect(url_for('admin_off_days'))
    
    # Get all off days
    weekly_off_days = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='weekly'
    ).order_by(OffDay.day_of_week).all()
    
    specific_off_days = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='specific'
    ).order_by(OffDay.specific_date).all()
    
    # Get upcoming off days (next 60 days)
    from datetime import timedelta
    sixty_days_later = date.today() + timedelta(days=60)
    upcoming_off_days = OffDay.query.filter(
        OffDay.salon_settings_id == salon_settings.id,
        OffDay.type == 'specific',
        OffDay.specific_date >= date.today(),
        OffDay.specific_date <= sixty_days_later
    ).order_by(OffDay.specific_date).all()
    
    # Generate calendar preview for next 30 days
    preview_calendar = []
    for i in range(30):
        day_date = date.today() + timedelta(days=i)
        
        # Check if this day is an off day
        is_off_day = False
        
        # Check weekly off days
        day_of_week = day_date.weekday()
        weekly_off = OffDay.query.filter_by(
            salon_settings_id=salon_settings.id,
            type='weekly',
            day_of_week=day_of_week
        ).first()
        
        # Check specific off days
        specific_off = OffDay.query.filter_by(
            salon_settings_id=salon_settings.id,
            type='specific',
            specific_date=day_date
        ).first()
        
        is_off_day = weekly_off is not None or specific_off is not None
        
        preview_calendar.append({
            'date': day_date,
            'is_off_day': is_off_day,
            'is_today': day_date == date.today()
        })
    
    return render_template('admin_off_days.html',
        salon_settings=salon_settings,
        weekly_off_days=weekly_off_days,
        specific_off_days=specific_off_days,
        upcoming_off_days=upcoming_off_days,
        preview_calendar=preview_calendar,
        today=date.today()
    )

@app.route('/api/check-off-day')
def api_check_off_day():
    """Check if a date is an off day"""
    date_str = request.args.get('date')
    
    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return jsonify({'error': 'Invalid date format'})
    
    salon_settings = SalonSettings.query.first()
    
    # Check weekly off days
    day_of_week = check_date.weekday()  # 0=Monday, 6=Sunday
    weekly_off = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='weekly',
        day_of_week=day_of_week
    ).first()
    
    # Check specific off days
    specific_off = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='specific',
        specific_date=check_date
    ).first()
    
    is_off_day = weekly_off is not None or specific_off is not None
    
    return jsonify({
        'date': date_str,
        'is_off_day': is_off_day,
        'weekly_off': weekly_off.to_dict() if weekly_off else None,
        'specific_off': specific_off.to_dict() if specific_off else None
    })

from sqlalchemy import text  # Add this import at the top of your file


if __name__ == '__main__':
    port = 5008
    print(f"🚀 Starting Hair Salon System...")
    print(f"🌐 Customer Portal: http://localhost:{port}")
    print(f"🔧 Admin Panel: http://localhost:{port}/admin-login")
    print(f"📋 Services Management: http://localhost:{port}/admin/services")
    print(f"🤖 Telegram Bot: {Config.TELEGRAM_BOT_LINK}")
    print(f"🔗 Telegram Webhook: http://localhost:{port}/telegram-webhook")
    app.run(debug=True, port=port)