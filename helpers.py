# helpers.py
from datetime import datetime, timedelta
import random
import string
import requests

# Import models
from models import db, Customer, Appointment, Referral, SalonSettings

# Remove any "from config import db" lines

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

def get_date_color(date):
    # Example implementation
    appointment_count = Appointment.query.filter(
        db.func.date(Appointment.appointment_time) == date,
        Appointment.status.in_(['pending', 'confirmed'])
    ).count()
    
    salon_settings = SalonSettings.query.first()
    max_appointments = salon_settings.max_daily_appointments
    
    if appointment_count >= max_appointments:
        return ('full', 'Full', appointment_count)  # 'full' = class name
    elif appointment_count >= max_appointments * 0.7:  # 70% full
        return ('medium', 'Few Left', appointment_count)  # 'medium' = class name
    else:
        return ('available', 'Available', appointment_count)  # 'available' = class name

def get_available_time_slots(date_obj):
    """Get available time slots for a given date"""
    from datetime import datetime, timedelta
    
    salon_settings = SalonSettings.query.first()
    
    if not salon_settings:
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
        db.func.date(Appointment.appointment_time) == date_obj,
        Appointment.status.in_(['pending', 'confirmed'])
    ).all()
    
    # Create list of booked time ranges
    booked_ranges = []
    for appointment in existing_appointments:
        appointment_end = appointment.appointment_time + timedelta(minutes=appointment.duration)
        booked_ranges.append({
            'start': appointment.appointment_time,
            'end': appointment_end
        })
    
    # Generate time slots
    time_slots = []
    current_dt = datetime.combine(date_obj, start_time)
    end_dt = datetime.combine(date_obj, end_time)
    appointment_duration = salon_settings.appointment_duration
    
    # Debug: Print working hours
    print(f"DEBUG: Working hours - Start: {start_time}, End: {end_time}")
    print(f"DEBUG: Appointment duration: {appointment_duration} minutes")
    print(f"DEBUG: Buffer time: {buffer} minutes")
    
    while current_dt + timedelta(minutes=appointment_duration) <= end_dt:
        slot_end = current_dt + timedelta(minutes=appointment_duration)
        
        # Check if slot conflicts with existing appointments
        slot_available = True
        for booked in booked_ranges:
            # Check for time overlap
            if (current_dt < booked['end'] and slot_end > booked['start']):
                slot_available = False
                break
        
        if slot_available:
            time_slots.append({
                'time': current_dt.strftime('%I:%M %p'),
                'datetime': current_dt
            })
        
        # Move to next slot (appointment duration + buffer)
        current_dt += timedelta(minutes=appointment_duration + buffer)
    
    print(f"DEBUG: Generated {len(time_slots)} time slots")
    return time_slots

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
                from models import PointsHistory
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

def send_telegram_to_customer(customer, message):
    """Send Telegram message to customer"""
    if customer and customer.telegram_id:
        telegram_chat = TelegramChat.query.filter_by(telegram_username=customer.telegram_id).first()
        if telegram_chat and telegram_chat.chat_id:
            return send_telegram_message(telegram_chat.chat_id, message)
    
    return None

def send_appointment_confirmation(customer, appointment):
    """Send appointment confirmation via Telegram"""
    end_time = appointment.end_time or appointment.appointment_time + timedelta(minutes=appointment.duration)
    
    message = f"""📅 *Appointment Confirmed!*

👤 *Customer:* {customer.name}
📱 *Phone:* {customer.phone}
💇 *Service:* {appointment.service_type}
📅 *Date:* {appointment.appointment_time.strftime('%d %b %Y')}
⏰ *Time:* {appointment.appointment_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}
💰 *Points used:* {appointment.points_deducted}
🎯 *Remaining points:* {customer.points}

✅ Please arrive 10 minutes before your appointment."""
    
    send_telegram_to_customer(customer, message)
    
    salon_settings = SalonSettings.query.first()
    if salon_settings.telegram_chat_id:
        admin_msg = f"📋 *New Appointment Booked!*\n\n👤 {customer.name}\n💇 {appointment.service_type}\n📅 {appointment.appointment_time.strftime('%d %b %Y %I:%M %p')}"
        send_telegram_message(salon_settings.telegram_chat_id, admin_msg)