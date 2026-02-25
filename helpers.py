from datetime import datetime, timedelta, date, time
import random
import string
import requests

# Import db from models instead of app
from models import db, SalonSettings, OffDay, Appointment, Customer, Referral, TelegramChat, PointsHistory
from sqlalchemy import func

def generate_referral_code(length=8):
    """Generate random referral code"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def normalize_phone_number(phone):
    """Normalize Malaysian phone numbers to +60 format"""
    if not phone:
        print(f"DEBUG: No phone provided")
        return None
    
    print(f"DEBUG: Original phone: '{phone}'")
    
    # Remove all spaces, dashes, parentheses
    phone = phone.strip()
    phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    print(f"DEBUG: After cleaning: '{phone}'")
    
    # Handle various Malaysian phone number formats
    
    # Case 1: Already in +60 format
    if phone.startswith('+60'):
        if len(phone) == 12:  # +60123456789
            print(f"DEBUG: Case 1 - Already +60 format: {phone}")
            return phone
        elif len(phone) == 13:  # +601234567890 (some might have extra digit)
            print(f"DEBUG: Case 1a - +60 with 10 digits: {phone}")
            return phone[:12]  # Trim to standard length
    
    # Case 2: Starts with 01 (most common user input)
    if phone.startswith('01'):
        if len(phone) == 10 or len(phone) == 11:  # 0123456789 or 01234567890
            normalized = '+60' + phone[1:]  # Remove leading 0
            print(f"DEBUG: Case 2 - 01 format: {phone} -> {normalized}")
            return normalized
    
    # Case 3: Starts with 1 (user forgot the 0)
    if phone.startswith('1'):
        if len(phone) == 9 or len(phone) == 10:  # 123456789 or 1234567890
            normalized = '+60' + phone
            print(f"DEBUG: Case 3 - 1 format: {phone} -> {normalized}")
            return normalized
    
    # Case 4: Starts with 60 (without +)
    if phone.startswith('60'):
        if len(phone) == 11 or len(phone) == 12:  # 60123456789 or 601234567890
            normalized = '+' + phone
            print(f"DEBUG: Case 4 - 60 format: {phone} -> {normalized}")
            return normalized
    
    # Case 5: Starts with 6 (short 60)
    if phone.startswith('6'):
        if len(phone) == 10 or len(phone) == 11:  # 6123456789 or 61234567890
            normalized = '+6' + phone[1:]  # Keep as +6 for backward compatibility
            print(f"DEBUG: Case 5 - 6 format: {phone} -> {normalized}")
            return normalized
    
    # Case 6: Already in +6 format (old format)
    if phone.startswith('+6'):
        print(f"DEBUG: Case 6 - Already +6 format: {phone}")
        return phone
    
    # If we get here, try to salvage
    print(f"DEBUG: Trying to salvage: {phone}")
    
    # Remove all non-digits except +
    digits = ''.join(c for c in phone if c.isdigit() or c == '+')
    
    if digits.startswith('0'):
        if len(digits) == 10 or len(digits) == 11:  # 0123456789
            normalized = '+60' + digits[1:]
            print(f"DEBUG: Salvaged 0 format: {digits} -> {normalized}")
            return normalized
    
    print(f"DEBUG: Could not normalize phone: '{phone}'")
    return None

def get_date_color(check_date):
    """Get color coding for calendar dates"""
    salon_settings = SalonSettings.query.first()
    
    # Check if it's an off day first
    if is_off_day(check_date):
        return 'off-day', 'OFF DAY', 0
    
    # Check if date is in the past
    today = date.today()
    if check_date < today:
        return 'past-date', 'PASSED', 0
    
    # Get appointment count for this date
    appointment_count = Appointment.query.filter(
        func.date(Appointment.appointment_time) == check_date,
        Appointment.status.in_(['pending', 'confirmed'])
    ).count()
    
    max_appointments = salon_settings.max_daily_appointments
    percentage = (appointment_count / max_appointments) * 100 if max_appointments > 0 else 0
    
    # Determine color and status based on availability
    if appointment_count == 0:
        return 'available', 'AVAILABLE', appointment_count
    elif percentage < 50:
        return 'available', 'AVAILABLE', appointment_count
    elif percentage < 80:
        return 'medium', 'LIMITED', appointment_count
    elif percentage < 100:
        return 'full', 'FEW LEFT', appointment_count
    else:
        return 'full', 'FULL', appointment_count

def is_off_day(check_date):
    """Check if a date is an off day"""
    salon_settings = SalonSettings.query.first()
    if not salon_settings:
        return False
    
    # Check weekly off days
    day_of_week = check_date.weekday()
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
    
    return weekly_off is not None or specific_off is not None

def get_available_time_slots(date_obj, service_duration=None):
    """
    Get available time slots for a specific date.
    If service_duration is provided, returns slots that can accommodate that duration.
    """
    # Check if it's an off day
    if is_off_day(date_obj):
        return []
    
    salon_settings = SalonSettings.query.first()
    
    if not salon_settings:
        return []
    
    # Check if it's an off day
    day_of_week = date_obj.weekday()
    
    # Check weekly off days
    weekly_off = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='weekly',
        day_of_week=day_of_week
    ).first()
    
    # Check specific off days
    specific_off = OffDay.query.filter_by(
        salon_settings_id=salon_settings.id,
        type='specific',
        specific_date=date_obj
    ).first()
    
    # If it's an off day, return empty list
    if weekly_off or specific_off:
        print(f"DEBUG: {date_obj} is an off day")
        return []
    
    # Get buffer time (default 15 minutes)
    buffer = getattr(salon_settings, 'buffer_time', 15)
    
    # Get working hours from settings
    try:
        start_time = datetime.strptime(salon_settings.working_hours_start, '%H:%M').time()
        end_time = datetime.strptime(salon_settings.working_hours_end, '%H:%M').time()
    except ValueError:
        # Default to 9 AM - 6 PM if format is wrong
        start_time = datetime.strptime('09:00', '%H:%M').time()
        end_time = datetime.strptime('18:00', '%H:%M').time()
    
    # Get existing appointments for this date
    existing_appointments = Appointment.query.filter(
        func.date(Appointment.appointment_time) == date_obj,
        Appointment.status.in_(['pending', 'confirmed'])
    ).order_by(Appointment.appointment_time).all()
    
    # Create list of busy intervals
    busy_intervals = []
    for apt in existing_appointments:
        apt_start = apt.appointment_time
        apt_end = apt.appointment_time + timedelta(minutes=apt.duration)
        busy_intervals.append((apt_start, apt_end))
    
    # Generate all possible time slots
    available_slots = []
    
    # Use provided service duration or default from settings
    slot_duration = service_duration if service_duration else salon_settings.appointment_duration
    
    # Start from the beginning of working hours
    current_dt = datetime.combine(date_obj, start_time)
    end_dt = datetime.combine(date_obj, end_time)
    
    # Debug: Print working hours
    print(f"DEBUG: Working hours - Start: {start_time}, End: {end_time}")
    print(f"DEBUG: Requested duration: {slot_duration} minutes")
    print(f"DEBUG: Buffer time: {buffer} minutes")
    print(f"DEBUG: Date: {date_obj}")
    
    # Generate slots in 15-minute increments
    while current_dt + timedelta(minutes=slot_duration) <= end_dt:
        slot_end = current_dt + timedelta(minutes=slot_duration)
        
        # Check if slot conflicts with existing appointments
        is_available = True
        for busy_start, busy_end in busy_intervals:
            # Check for overlap
            if not (slot_end <= busy_start or current_dt >= busy_end):
                is_available = False
                break
        
        if is_available:
            available_slots.append({
                'time': current_dt.strftime('%I:%M %p'),
                'datetime': current_dt,
                'end_time': slot_end.strftime('%I:%M %p'),
                'duration': slot_duration
            })
            # Move to next slot (15 minutes)
            current_dt += timedelta(minutes=15)
        else:
            # Move to next 15-minute slot
            current_dt += timedelta(minutes=15)
    
    print(f"DEBUG: Generated {len(available_slots)} time slots for {slot_duration}min service")
    return available_slots

def award_referral_points(referred_id):
    """Award referral points when a referred customer completes their first appointment"""
    try:
        # Find the referral record
        referral = Referral.query.filter_by(
            referred_id=referred_id,
            status='pending'
        ).first()
        
        if referral:
            # Update referral status
            referral.status = 'completed'
            
            # Award points to referrer
            referrer = Customer.query.get(referral.referrer_id)
            if referrer:
                # Store old points
                old_points = referrer.points
                
                # Award points
                referrer.points += 10  # Award 10 points for successful referral
                
                # Log to points history
                points_history = PointsHistory(
                    customer_id=referrer.id,
                    old_points=old_points,
                    new_points=referrer.points,
                    difference=10,
                    reason=f'Referral bonus for customer ID: {referred_id}',
                    changed_by='system'
                )
                db.session.add(points_history)
                
                # Send notification to referrer
                if referrer.telegram_id:
                    message = f"🎉 Referral bonus! You earned 10 points for referring a customer!"
                    send_telegram_to_customer(referrer, message)
                
                return True
    except Exception as e:
        print(f"Error awarding referral points: {e}")
    
    return False

def send_telegram_message(chat_id, message):
    """Send message to Telegram chat"""
    salon_settings = SalonSettings.query.first()
    if not salon_settings or not salon_settings.telegram_bot_token:
        print(f"No Telegram bot token configured")
        return False
    
    bot_token = salon_settings.telegram_bot_token
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False

def send_welcome_message(chat_id, first_name):
    """Send welcome message when user starts bot"""
    message = f"""👋 Hello {first_name}!

Welcome to <b>HS Salon Booking System</b>!

I will send you:
✅ Appointment confirmations
✅ Reminders before your appointment  
✅ Points updates and rewards
✅ Referral notifications

You're now connected to receive notifications!"""
    
    return send_telegram_message(chat_id, message)

def send_telegram_to_customer(customer, message):
    """Send message to customer via Telegram"""
    if customer.telegram_id:
        return send_telegram_message(customer.telegram_id, message)
    return False

def send_appointment_confirmation(customer, appointment):
    """Send appointment confirmation via Telegram"""
    end_time = appointment.end_time or appointment.appointment_time + timedelta(minutes=appointment.duration)
    
    message = f"""📅 *Appointment Confirmed!*

👤 *Customer:* {customer.name}
📱 *Phone:* {customer.phone}
💇 *Service:* {appointment.service_type}
📅 *Date:* {appointment.appointment_time.strftime('%d %b %Y')}
⏰ *Time:* {appointment.appointment_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}
⏱️ *Duration:* {appointment.duration} minutes
💰 *Points used:* {appointment.points_deducted}
🎯 *Remaining points:* {customer.points}

✅ Please arrive 10 minutes before your appointment."""
    
    send_telegram_to_customer(customer, message)
    
    salon_settings = SalonSettings.query.first()
    if salon_settings and salon_settings.telegram_chat_id:
        admin_msg = f"📋 *New Appointment Booked!*\n\n👤 {customer.name}\n💇 {appointment.service_type}\n⏱️ {appointment.duration} min\n📅 {appointment.appointment_time.strftime('%d %b %Y %I:%M %p')}"
        send_telegram_message(salon_settings.telegram_chat_id, admin_msg)