from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.db.models import Q, Count, Avg
from django.utils import timezone
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
from datetime import datetime, timedelta
import json

from .models import Doctor, Appointment, Profile, Notification, StatusHistory, DoctorSchedule, PatientNotes, Review, AppointmentReminder, TimeBlock


# ---------------- HOME ----------------

def home(request):
    total_appointments = Appointment.objects.count()
    total_doctors = Doctor.objects.filter(is_active=True).count()
    upcoming_appointments = Appointment.objects.filter(
        appointment_date__gte=timezone.now().date(),
        status__in=['approved', 'scheduled']
    ).count()

    featured_doctors = Doctor.objects.filter(is_active=True)[:6]

    # 🔹 ADD THIS
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()

    context = {
        'total_appointments': total_appointments,
        'total_doctors': total_doctors,
        'upcoming_appointments': upcoming_appointments,
        'featured_doctors': featured_doctors,
        'unread_notifications': unread_notifications,  # ✅
    }

    return render(request, 'home_enhanced.html', context)



# ---------------- DOCTORS LIST ----------------
def doctors(request):
    """Enhanced doctors list with filtering and search"""
    specialization = request.GET.get('specialization', '')
    search_query = request.GET.get('search', '')
    
    doctors = Doctor.objects.filter(is_active=True)
    
    if specialization:
        doctors = doctors.filter(specialization=specialization)
    
    if search_query:
        doctors = doctors.filter(
            Q(name__icontains=search_query) | 
            Q(specialization__icontains=search_query)
        )
    
    # Get available specializations
    specializations = Doctor.objects.filter(is_active=True).values_list(
        'specialization', flat=True
    ).distinct().order_by('specialization')
    
    # Get unread notifications count
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'doctors': doctors,
        'specializations': specializations,
        'current_specialization': specialization,
        'search_query': search_query,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'doctors.html', context)


# ---------------- BOOK APPOINTMENT ----------------
@login_required
def book_appointment(request, doctor_id):
    """Enhanced appointment booking with conflict checking and notifications"""
    try:
        profile = request.user.profile
        if profile.role != 'patient':
            messages.error(request, "Only patients can book appointments.")
            return redirect('doctors')
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found. Please contact support.")
        return redirect('home')

    doctor = get_object_or_404(Doctor, id=doctor_id)

    if request.method == 'POST':
        date = request.POST.get('date')
        time = request.POST.get('time')
        reason = request.POST.get('reason', '')
        priority = request.POST.get('priority', 'normal')

        # Validate input
        if not date or not time:
            messages.error(request, "All fields are required.")
            return redirect('book', doctor_id=doctor.id)

        # Check for time conflicts
        conflict_exists = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=date,
            appointment_time=time,
            status__in=['pending', 'approved', 'scheduled']
        ).exists()

        if conflict_exists:
            messages.error(request, "This time slot is already booked. Please choose another time.")
            return redirect('book', doctor_id=doctor.id)

        try:
            # Create appointment
            appointment = Appointment.objects.create(
                patient_name=request.user.username,
                patient_email=request.user.email,
                patient_phone=profile.phone,
                doctor=doctor,
                appointment_date=date,
                appointment_time=time,
                reason=reason,
                priority=priority,
                status='pending',
                user=request.user
            )

            # Note: Notification creation is handled by signals.py post_save signal
            # No need to create notification here to avoid duplicates

            messages.success(
                request,
                "Appointment booked successfully! Waiting for doctor approval."
            )
            return redirect('patient_dashboard')
            
        except Exception as e:
            # Log the error and show a user-friendly message
            messages.error(
                request,
                f"An error occurred while booking the appointment. Please try again. Error: {str(e)}"
            )
            return redirect('book', doctor_id=doctor.id)

    # Get available time slots for the doctor
    available_slots = get_available_time_slots(doctor, request.GET.get('date'))
    
    # Get unread notifications count
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'doctor': doctor,
        'available_slots': available_slots,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'book.html', context)


# ---------------- DASHBOARD VIEWS ----------------
@login_required
def patient_dashboard(request):
    """Patient dashboard with appointment history and management"""
    try:
        profile = request.user.profile
        if profile.role != 'patient':
            return HttpResponseForbidden("Access denied. Patients only.")
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')

    # Get patient's appointments
    appointments = Appointment.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # Filter by status if requested
    status_filter = request.GET.get('status', '')
    if status_filter:
        appointments = appointments.filter(status=status_filter)

    # Get notifications
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:10]

    # Get upcoming appointments
    upcoming_appointments = appointments.filter(
        appointment_date__gte=timezone.now().date(),
        status__in=['approved', 'scheduled']
    )

    # Statistics
    total_appointments = appointments.count()
    completed_appointments = appointments.filter(status='completed').count()
    cancelled_appointments = appointments.filter(status='cancelled').count()

    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()

    context = {
        'appointments': appointments,
        'notifications': notifications,
        'upcoming_appointments': upcoming_appointments,
        'total_appointments': total_appointments,
        'completed_appointments': completed_appointments,
        'cancelled_appointments': cancelled_appointments,
        'status_filter': status_filter,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'patient_dashboard.html', context)


@login_required
def doctor_dashboard(request):
    """Doctor dashboard with appointment management"""
    try:
        profile = request.user.profile
        if profile.role != 'doctor':
            return HttpResponseForbidden("Access denied. Doctors only.")
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')

    # Get doctor's appointments
    doctor = get_object_or_404(Doctor, name=request.user.username)
    appointments = Appointment.objects.filter(
        doctor=doctor
    ).order_by('-created_at')

    # Filter by status if requested
    status_filter = request.GET.get('status', '')
    if status_filter:
        appointments = appointments.filter(status=status_filter)

    # Get notifications
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:10]

    # Get upcoming appointments
    upcoming_appointments = appointments.filter(
        appointment_date__gte=timezone.now().date(),
        status__in=['approved', 'scheduled']
    )

    # Statistics
    total_appointments = appointments.count()
    pending_appointments = appointments.filter(status='pending').count()
    completed_appointments = appointments.filter(status='completed').count()

    # Recent activity
    recent_appointments = appointments[:5]

    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()

    context = {
        'appointments': appointments,
        'notifications': notifications,
        'upcoming_appointments': upcoming_appointments,
        'recent_appointments': recent_appointments,
        'total_appointments': total_appointments,
        'pending_appointments': pending_appointments,
        'completed_appointments': completed_appointments,
        'status_filter': status_filter,
        'doctor': doctor,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'doctor_dashboard.html', context)


# ---------------- APPOINTMENT MANAGEMENT ----------------
@login_required
def update_appointment_status(request, appointment_id):
    """Update appointment status with history tracking"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    appointment = get_object_or_404(Appointment, id=appointment_id)
    
    # Check permissions
    try:
        profile = request.user.profile
        if profile.role == 'patient':
            # Patients can only cancel their own appointments
            if appointment.user != request.user:
                return JsonResponse({'error': 'Permission denied'}, status=403)
            if request.POST.get('status') not in ['cancelled']:
                return JsonResponse({'error': 'Patients can only cancel appointments'}, status=403)
        elif profile.role == 'doctor':
            # Doctors can update status for their appointments
            doctor = Doctor.objects.get(name=request.user.username)
            if appointment.doctor != doctor:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        else:
            return JsonResponse({'error': 'Permission denied'}, status=403)
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)

    new_status = request.POST.get('status')
    reason = request.POST.get('reason', '')

    # Validate status transition
    if new_status not in dict(Appointment.STATUS_CHOICES):
        return JsonResponse({'error': 'Invalid status'}, status=400)

    old_status = appointment.status
    appointment.status = new_status
    appointment.updated_at = timezone.now()

    # Set additional timestamps based on status
    if new_status == 'approved':
        appointment.confirmed_at = timezone.now()
    elif new_status == 'completed':
        appointment.completed_at = timezone.now()
    elif new_status == 'cancelled':
        appointment.cancellation_reason = reason

    appointment.save()

    # Create status history record
    StatusHistory.objects.create(
        appointment=appointment,
        old_status=old_status,
        new_status=new_status,
        changed_by=request.user,
        reason=reason
    )

    # Create notifications
    if new_status != old_status:
        # Notify patient
        if appointment.user:
            Notification.objects.create(
                user=appointment.user,
                appointment=appointment,
                type='status_changed',
                title=f'Appointment Status Updated',
                message=f'Your appointment status has been changed from {old_status} to {new_status}.'
            )

    return JsonResponse({
        'success': True,
        'new_status': new_status,
        'message': 'Status updated successfully'
    })


@login_required
def reschedule_appointment(request, appointment_id):
    """Reschedule an appointment"""
    appointment = get_object_or_404(Appointment, id=appointment_id)
    
    # Check permissions
    if appointment.user != request.user:
        return HttpResponseForbidden("Permission denied")
    
    if not appointment.can_be_rescheduled():
        messages.error(request, "This appointment cannot be rescheduled.")
        return redirect('patient_dashboard')

    if request.method == 'POST':
        new_date = request.POST.get('date')
        new_time = request.POST.get('time')

        # Check for conflicts
        conflict_exists = Appointment.objects.filter(
            doctor=appointment.doctor,
            appointment_date=new_date,
            appointment_time=new_time,
            status__in=['pending', 'approved', 'scheduled']
        ).exclude(id=appointment.id).exists()

        if conflict_exists:
            messages.error(request, "The selected time slot is not available.")
            return redirect('reschedule_appointment', appointment_id=appointment.id)

        # Update appointment
        old_date = appointment.appointment_date
        old_time = appointment.appointment_time
        
        appointment.appointment_date = new_date
        appointment.appointment_time = new_time
        appointment.status = 'rescheduled'
        appointment.updated_at = timezone.now()
        appointment.save()

        # Create history record
        StatusHistory.objects.create(
            appointment=appointment,
            old_status='scheduled',
            new_status='rescheduled',
            changed_by=request.user,
            reason=f'Rescheduled from {old_date} {old_time} to {new_date} {new_time}'
        )

        messages.success(request, "Appointment rescheduled successfully!")
        return redirect('patient_dashboard')

    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()

    return render(request, 'reschedule_appointment.html', {
        'appointment': appointment,
        'unread_notifications': unread_notifications
    })


# ---------------- NOTIFICATION MANAGEMENT ----------------
@login_required
def mark_notification_read(request, notification_id):
    """Mark a notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('patient_dashboard' if request.user.profile.role == 'patient' else 'doctor_dashboard')


@login_required
def mark_all_notifications_read(request):
    """Mark all notifications as read"""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('patient_dashboard' if request.user.profile.role == 'patient' else 'doctor_dashboard')


# ---------------- API ENDPOINTS ----------------
@login_required
def get_available_slots(request):
    """Get available time slots for a doctor on a specific date"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    doctor_id = request.GET.get('doctor_id')
    date = request.GET.get('date')

    if not doctor_id or not date:
        return JsonResponse({'error': 'Doctor ID and date are required'}, status=400)

    try:
        doctor = Doctor.objects.get(id=doctor_id)
    except Doctor.DoesNotExist:
        return JsonResponse({'error': 'Doctor not found'}, status=404)

    slots = get_available_time_slots(doctor, date)
    return JsonResponse({'slots': slots})


@login_required
def get_appointment_details(request, appointment_id):
    """Get detailed information about an appointment"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        appointment = Appointment.objects.get(id=appointment_id)
        
        # Check permissions
        profile = request.user.profile
        if profile.role == 'patient' and appointment.user != request.user:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        elif profile.role == 'doctor':
            doctor = Doctor.objects.get(name=request.user.username)
            if appointment.doctor != doctor:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Prepare response data
        data = {
            'success': True,
            'appointment': {
                'id': appointment.id,
                'patient_name': appointment.patient_name,
                'patient_email': appointment.patient_email,
                'patient_phone': appointment.patient_phone,
                'appointment_date': appointment.appointment_date.strftime('%Y-%m-%d'),
                'appointment_time': appointment.appointment_time.strftime('%H:%M'),
                'status': appointment.status,
                'priority': appointment.priority,
                'reason': appointment.reason,
                'notes': appointment.notes,
                'created_at': appointment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'status_history': [
                    {
                        'old_status': h.old_status,
                        'new_status': h.new_status,
                        'reason': h.reason,
                        'changed_at': h.changed_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'changed_by': h.changed_by.username if h.changed_by else 'System'
                    }
                    for h in appointment.status_history.all()
                ]
            }
        }
        
        return JsonResponse(data)
        
    except Appointment.DoesNotExist:
        return JsonResponse({'error': 'Appointment not found'}, status=404)


# ---------------- SEARCH AND FILTERING ----------------
@login_required
def search_appointments(request):
    """Search and filter appointments"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Base queryset based on user role
    try:
        profile = request.user.profile
        if profile.role == 'patient':
            appointments = Appointment.objects.filter(user=request.user)
        elif profile.role == 'doctor':
            doctor = Doctor.objects.get(name=request.user.username)
            appointments = Appointment.objects.filter(doctor=doctor)
        else:
            appointments = Appointment.objects.all()
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)

    # Apply filters
    if query:
        appointments = appointments.filter(
            Q(patient_name__icontains=query) |
            Q(reason__icontains=query) |
            Q(doctor__name__icontains=query)
        )

    if status:
        appointments = appointments.filter(status=status)

    if date_from:
        appointments = appointments.filter(appointment_date__gte=date_from)

    if date_to:
        appointments = appointments.filter(appointment_date__lte=date_to)

    appointments = appointments.order_by('-created_at')[:20]

    # Serialize results
    results = []
    for appointment in appointments:
        results.append({
            'id': appointment.id,
            'patient_name': appointment.patient_name,
            'doctor_name': appointment.doctor.name,
            'appointment_date': appointment.appointment_date.strftime('%Y-%m-%d'),
            'appointment_time': appointment.appointment_time.strftime('%H:%M'),
            'status': appointment.status,
            'priority': appointment.priority,
        })

    return JsonResponse({'appointments': results})


# ---------------- BULK OPERATIONS ----------------
@login_required
def bulk_update_appointments(request):
    """Bulk update multiple appointments (for doctors)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        profile = request.user.profile
        if profile.role != 'doctor':
            return JsonResponse({'error': 'Permission denied'}, status=403)
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)

    appointment_ids = request.POST.getlist('appointment_ids[]')
    new_status = request.POST.get('status')
    reason = request.POST.get('reason', '')

    if not appointment_ids or not new_status:
        return JsonResponse({'error': 'Appointment IDs and new status are required'}, status=400)

    if new_status not in dict(Appointment.STATUS_CHOICES):
        return JsonResponse({'error': 'Invalid status'}, status=400)

    try:
        doctor = Doctor.objects.get(name=request.user.username)
        updated_count = 0

        for appointment_id in appointment_ids:
            try:
                appointment = Appointment.objects.get(
                    id=appointment_id,
                    doctor=doctor
                )
                
                old_status = appointment.status
                appointment.status = new_status
                appointment.updated_at = timezone.now()

                # Set additional timestamps
                if new_status == 'approved':
                    appointment.confirmed_at = timezone.now()
                elif new_status == 'completed':
                    appointment.completed_at = timezone.now()
                elif new_status == 'cancelled':
                    appointment.cancellation_reason = reason

                appointment.save()

                # Create history record
                StatusHistory.objects.create(
                    appointment=appointment,
                    old_status=old_status,
                    new_status=new_status,
                    changed_by=request.user,
                    reason=reason or f'Bulk update: {old_status} → {new_status}'
                )

                # Create notification
                if appointment.user:
                    Notification.objects.create(
                        user=appointment.user,
                        appointment=appointment,
                        type='status_changed',
                        title='Appointment Status Updated',
                        message=f'Your appointment has been {new_status} (bulk update).'
                    )

                updated_count += 1

            except Appointment.DoesNotExist:
                continue

        return JsonResponse({
            'success': True,
            'updated_count': updated_count,
            'message': f'Successfully updated {updated_count} appointments'
        })

    except Doctor.DoesNotExist:
        return JsonResponse({'error': 'Doctor profile not found'}, status=404)


# ---------------- EXPORT FUNCTIONALITY ----------------
@login_required
def export_appointments(request):
    """Export appointments to CSV/Excel format"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    format_type = request.GET.get('format', 'csv')
    
    try:
        profile = request.user.profile
        if profile.role == 'patient':
            appointments = Appointment.objects.filter(user=request.user)
        elif profile.role == 'doctor':
            doctor = Doctor.objects.get(name=request.user.username)
            appointments = Appointment.objects.filter(doctor=doctor)
        else:
            appointments = Appointment.objects.all()
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)

    # Apply filters
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if status_filter:
        appointments = appointments.filter(status=status_filter)
    if date_from:
        appointments = appointments.filter(appointment_date__gte=date_from)
    if date_to:
        appointments = appointments.filter(appointment_date__lte=date_to)

    appointments = appointments.order_by('-created_at')

    if format_type == 'csv':
        return export_to_csv(appointments)
    elif format_type == 'json':
        return export_to_json(appointments)
    else:
        return JsonResponse({'error': 'Unsupported format'}, status=400)


def export_to_csv(appointments):
    """Export appointments to CSV format"""
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="appointments_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Patient Name', 'Patient Email', 'Doctor', 'Date', 'Time', 
        'Status', 'Priority', 'Reason', 'Created At'
    ])

    for appointment in appointments:
        writer.writerow([
            appointment.id,
            appointment.patient_name,
            appointment.patient_email,
            appointment.doctor.name,
            appointment.appointment_date,
            appointment.appointment_time,
            appointment.get_status_display(),
            appointment.get_priority_display(),
            appointment.reason or '',
            appointment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])

    return response


def export_to_json(appointments):
    """Export appointments to JSON format"""
    from django.http import JsonResponse
    import json

    data = []
    for appointment in appointments:
        data.append({
            'id': appointment.id,
            'patient_name': appointment.patient_name,
            'patient_email': appointment.patient_email,
            'doctor_name': appointment.doctor.name,
            'appointment_date': appointment.appointment_date.strftime('%Y-%m-%d'),
            'appointment_time': appointment.appointment_time.strftime('%H:%M'),
            'status': appointment.get_status_display(),
            'priority': appointment.get_priority_display(),
            'reason': appointment.reason,
            'created_at': appointment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    response = JsonResponse({'appointments': data})
    response['Content-Disposition'] = f'attachment; filename="appointments_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
    return response


# ---------------- ANALYTICS AND REPORTING ----------------
@login_required
def analytics_dashboard(request):
    """Analytics dashboard for doctors and admins"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        profile = request.user.profile
        if profile.role not in ['doctor', 'admin']:
            return JsonResponse({'error': 'Permission denied'}, status=403)
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)

    # Get date range (default to last 30 days)
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    # Base queryset
    if profile.role == 'doctor':
        doctor = Doctor.objects.get(name=request.user.username)
        appointments = Appointment.objects.filter(
            doctor=doctor,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )
    else:
        appointments = Appointment.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

    # Calculate statistics
    total_appointments = appointments.count()
    status_counts = {}
    for status, _ in Appointment.STATUS_CHOICES:
        status_counts[status] = appointments.filter(status=status).count()

    # Monthly trends
    monthly_data = []
    for i in range(min(days, 30)):
        date = end_date - timedelta(days=i)
        day_appointments = appointments.filter(created_at__date=date).count()
        monthly_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'appointments': day_appointments
        })

    # Priority distribution
    priority_counts = {}
    for priority, _ in Appointment.PRIORITY_CHOICES:
        priority_counts[priority] = appointments.filter(priority=priority).count()

    # Success rate
    completed_appointments = status_counts.get('completed', 0)
    success_rate = (completed_appointments / total_appointments * 100) if total_appointments > 0 else 0

    data = {
        'period': {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'days': days
        },
        'overview': {
            'total_appointments': total_appointments,
            'success_rate': round(success_rate, 2),
            'completed_appointments': completed_appointments,
            'cancelled_appointments': status_counts.get('cancelled', 0),
        },
        'status_distribution': status_counts,
        'priority_distribution': priority_counts,
        'daily_trends': list(reversed(monthly_data)),  # Chronological order
        'top_doctors': [] if profile.role == 'doctor' else get_top_doctors(start_date, end_date),
    }

    return JsonResponse(data)


def get_top_doctors(start_date, end_date):
    """Get top performing doctors in the given period"""
    from django.db.models import Count

    top_doctors = Doctor.objects.annotate(
        appointment_count=Count('appointment', filter=Q(
            appointment__created_at__date__gte=start_date,
            appointment__created_at__date__lte=end_date
        ))
    ).filter(appointment_count__gt=0).order_by('-appointment_count')[:5]

    return [{
        'name': doctor.name,
        'specialization': doctor.specialization,
        'appointment_count': doctor.appointment_count
    } for doctor in top_doctors]


# ---------------- UTILITY FUNCTIONS ----------------
def send_activation_email(request, user):
    """Send an activation email with a one-time verification link."""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    activation_url = request.build_absolute_uri(
        reverse('activate_account', args=[uid, token])
    )

    subject = "Verify your email to activate your account"
    plain_message = (
        f"Hi {user.username},\n\n"
        f"Please verify your email to activate your account: {activation_url}\n\n"
        "If you did not create an account, you can ignore this email."
    )

    html_message = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2563eb;">Activate your account</h2>
            <p>Hi {user.username},</p>
            <p>Thanks for signing up. Please confirm your email to activate your account.</p>
            <div style="margin: 24px 0; text-align: center;">
                <a href="{activation_url}" style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">Verify Email</a>
            </div>
            <p>If the button does not work, copy and paste this link into your browser:</p>
            <p><a href="{activation_url}">{activation_url}</a></p>
            <p style="color: #6b7280; font-size: 12px;">If you did not create an account, please ignore this message.</p>
        </div>
    </body>
    </html>
    """

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )


def get_available_time_slots(doctor, date):
    """Get available time slots for a doctor on a specific date"""
    if not date:
        return []
    
    # This is a simplified version - in production you'd want more sophisticated logic
    booked_slots = Appointment.objects.filter(
        doctor=doctor,
        appointment_date=date,
        status__in=['pending', 'approved', 'scheduled']
    ).values_list('appointment_time', flat=True)
    
    # Generate available slots (9 AM to 5 PM, 1-hour slots)
    available_slots = []
    from datetime import time
    current_time = time(9, 0)  # 9 AM
    end_time = time(17, 0)     # 5 PM
    
    while current_time < end_time:
        if current_time not in booked_slots:
            available_slots.append(current_time.strftime('%H:%M'))
        # Add 1 hour
        from datetime import datetime, timedelta
        current_dt = datetime.combine(datetime.today(), current_time)
        current_dt += timedelta(hours=1)
        current_time = current_dt.time()
    
    return available_slots


def activate_account(request, uidb64, token):
    """Activate a user account after email verification."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, TypeError, ValueError, OverflowError):
        user = None

    if user and default_token_generator.check_token(user, token):
        if not user.is_active:
            user.is_active = True
            user.save()

        profile, _ = Profile.objects.get_or_create(user=user)
        if not profile.email_verified:
            profile.email_verified = True
            profile.save()

        if profile.role == 'doctor':
            Doctor.objects.filter(name=user.username).update(email_verified=True)

        messages.success(request, "Email verified successfully. You are now signed in.")
        login(request, user)
        return redirect('home')

    messages.error(request, "Activation link is invalid or has expired.")
    return redirect('login')


# ---------------- PATIENT SIGNUP ----------------
def signup_patient(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')

        if not username or not password or not email:
            messages.error(request, "Username, password, and email are required for verification.")
            return redirect('signup_patient')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('signup_patient')

        if User.objects.filter(email=email).exists():
            messages.error(request, "An account with that email already exists.")
            return redirect('signup_patient')

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email
        )
        user.is_active = False
        user.save()

        # Create profile with enhanced fields
        profile, created = Profile.objects.get_or_create(user=user)
        profile.role = 'patient'
        profile.phone = phone
        profile.email_verified = False
        profile.save()

        send_activation_email(request, user)

        messages.success(
            request,
            "Account created. Check your email for the verification link to activate your profile."
        )
        return redirect('login')

    # Get unread notifications count (0 for non-authenticated users)
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()

    context = {
        'unread_notifications': unread_notifications,
    }
    return render(request, 'signup_patient.html', context)


# ---------------- DOCTOR SIGNUP ----------------
def signup_doctor(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        specialization = request.POST.get('specialization')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        consultation_fee = request.POST.get('consultation_fee', '0')
        experience_years = request.POST.get('experience_years', '0')
        description = request.POST.get('description', '')
        affiliation = request.POST.get('affiliation', '')
        license_number = request.POST.get('license_number', '')
        email_notifications = request.POST.get('email_notifications') == 'true'
        sms_notifications = request.POST.get('sms_notifications') == 'true'
        terms_accepted = request.POST.get('terms_accepted') == 'on'

        # Validation
        if not username or not password or not specialization or not email:
            messages.error(request, "Username, password, email, and specialization are required.")
            return redirect('signup_doctor')

        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect('signup_doctor')

        if not terms_accepted:
            messages.error(request, "You must accept the terms and conditions.")
            return redirect('signup_doctor')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('signup_doctor')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return redirect('signup_doctor')

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email
            )
            user.is_active = False
            user.save()

            # Create profile
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = 'doctor'
            profile.specialization = specialization
            profile.phone = phone
            profile.email_verified = False
            profile.save()

            # Create doctor record
            doctor = Doctor.objects.create(
                name=username,
                specialization=specialization,
                email=email,
                phone=phone,
                consultation_fee=float(consultation_fee) if consultation_fee else 0,
                experience_years=int(experience_years) if experience_years else 0,
                description=description,
                affiliation=affiliation,
                license_number=license_number,
                email_notifications=email_notifications,
                sms_notifications=sms_notifications,
                is_active=False  # Requires verification
            )

            # Create default schedule for weekdays
            default_schedule = [
                ('monday', '09:00', '17:00'),
                ('tuesday', '09:00', '17:00'),
                ('wednesday', '09:00', '17:00'),
                ('thursday', '09:00', '17:00'),
                ('friday', '09:00', '17:00'),
                ('saturday', '10:00', '14:00'),
            ]
            for day, start, end in default_schedule:
                DoctorSchedule.objects.create(
                    doctor=doctor,
                    day_of_week=day,
                    start_time=start,
                    end_time=end,
                    is_available=True,
                    max_appointments=8,
                    slot_duration=30
                )

            send_activation_email(request, user)

            messages.success(
                request,
                "Doctor account created. Check your email to verify and activate your login."
            )

            # Redirect to login so they can sign in after verification
            return redirect('login')

        except Exception as e:
            # Clean up if there was an error
            if 'user' in locals():
                user.delete()
            if 'doctor' in locals():
                doctor.delete()
            messages.error(request, f"An error occurred: {str(e)}. Please try again.")
            return redirect('signup_doctor')

    # Get unread notifications count (0 for non-authenticated users)
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()

    context = {
        'unread_notifications': unread_notifications,
    }
    return render(request, 'signup_doctor.html', context)


# ================= NEW FEATURES =================

# ---------------- REVIEWS & RATINGS ----------------
@login_required
def doctor_detail(request, doctor_id):
    """Doctor detail page with reviews"""
    doctor = get_object_or_404(Doctor, id=doctor_id, is_active=True)
    
    # Get approved reviews
    reviews = Review.objects.filter(doctor=doctor, is_approved=True).order_by('-created_at')
    
    # Calculate rating distribution
    rating_distribution = {}
    for i in range(1, 6):
        rating_distribution[i] = reviews.filter(rating=i).count()
    
    # Check if current user can review (has completed appointment)
    can_review = False
    user_review = None
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            if profile.role == 'patient':
                # Check for completed appointments
                completed_appointments = Appointment.objects.filter(
                    user=request.user,
                    doctor=doctor,
                    status='completed'
                )
                if completed_appointments.exists():
                    # Check if user already reviewed this doctor
                    user_review = Review.objects.filter(
                        doctor=doctor,
                        patient=request.user
                    ).first()
                    can_review = True if not user_review else False
        except Profile.DoesNotExist:
            pass
    
    # Get unread notifications count
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'doctor': doctor,
        'reviews': reviews[:10],  # Show latest 10 reviews
        'rating_distribution': rating_distribution,
        'can_review': can_review,
        'user_review': user_review,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'doctor_detail.html', context)


@login_required
def add_review(request, doctor_id):
    """Add a review for a doctor"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    doctor = get_object_or_404(Doctor, id=doctor_id)
    
    try:
        profile = request.user.profile
        if profile.role != 'patient':
            return JsonResponse({'error': 'Only patients can leave reviews'}, status=403)
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)
    
    # Check if user has completed appointment with this doctor
    completed_appointments = Appointment.objects.filter(
        user=request.user,
        doctor=doctor,
        status='completed'
    )
    
    if not completed_appointments.exists():
        return JsonResponse({'error': 'You must have a completed appointment to review this doctor'}, status=400)
    
    # Check if user already reviewed
    existing_review = Review.objects.filter(doctor=doctor, patient=request.user).first()
    if existing_review:
        return JsonResponse({'error': 'You have already reviewed this doctor'}, status=400)
    
    rating = request.POST.get('rating')
    title = request.POST.get('title', '')
    comment = request.POST.get('comment', '')
    
    if not rating or int(rating) < 1 or int(rating) > 5:
        return JsonResponse({'error': 'Please provide a valid rating (1-5 stars)'}, status=400)
    
    if not comment:
        return JsonResponse({'error': 'Please provide a review comment'}, status=400)
    
    try:
        review = Review.objects.create(
            doctor=doctor,
            patient=request.user,
            appointment=completed_appointments.first(),
            rating=int(rating),
            title=title,
            comment=comment,
            is_approved=False  # Require approval
        )
        
        # Update doctor rating
        doctor.update_rating()
        
        return JsonResponse({
            'success': True,
            'message': 'Review submitted successfully! It will be visible after approval.'
        })
    except Exception as e:
        return JsonResponse({'error': f'Error submitting review: {str(e)}'}, status=500)


@login_required
def my_reviews(request):
    """View all reviews by the current patient"""
    try:
        profile = request.user.profile
        if profile.role != 'patient':
            return HttpResponseForbidden("Only patients can view their reviews")
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')
    
    reviews = Review.objects.filter(patient=request.user).order_by('-created_at')
    
    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'reviews': reviews,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'my_reviews.html', context)


@login_required
def edit_review(request, review_id):
    """Edit an existing review"""
    review = get_object_or_404(Review, id=review_id, patient=request.user)
    
    if request.method == 'POST':
        rating = request.POST.get('rating')
        title = request.POST.get('title', '')
        comment = request.POST.get('comment', '')
        
        if not rating or int(rating) < 1 or int(rating) > 5:
            messages.error(request, 'Please provide a valid rating (1-5 stars)')
            return redirect('edit_review', review_id=review.id)
        
        if not comment:
            messages.error(request, 'Please provide a review comment')
            return redirect('edit_review', review_id=review.id)
        
        review.rating = int(rating)
        review.title = title
        review.comment = comment
        review.is_approved = False  # Require re-approval after edit
        review.save()
        
        # Update doctor rating
        review.doctor.update_rating()
        
        messages.success(request, 'Review updated successfully!')
        return redirect('my_reviews')
    
    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'review': review,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'edit_review.html', context)


# ---------------- CALENDAR VIEW ----------------
@login_required
def appointment_calendar(request):
    """Calendar view for appointments"""
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')
    
    if profile.role == 'doctor':
        doctor = get_object_or_404(Doctor, name=request.user.username)
        appointments = Appointment.objects.filter(doctor=doctor)
    elif profile.role == 'patient':
        appointments = Appointment.objects.filter(user=request.user)
    else:
        appointments = Appointment.objects.all()
    
    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'appointments': appointments,
        'unread_notifications': unread_notifications,
        'role': profile.role,
    }
    return render(request, 'calendar.html', context)


@login_required
def calendar_events(request):
    """API endpoint for calendar events"""
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Profile not found'}, status=404)
    
    if profile.role == 'doctor':
        doctor = get_object_or_404(Doctor, name=request.user.username)
        appointments = Appointment.objects.filter(doctor=doctor)
    elif profile.role == 'patient':
        appointments = Appointment.objects.filter(user=request.user)
    else:
        appointments = Appointment.objects.all()
    
    # Format for FullCalendar
    events = []
    for apt in appointments:
        # Color based on status
        status_colors = {
            'pending': '#f59e0b',
            'approved': '#3b82f6',
            'scheduled': '#10b981',
            'completed': '#6b7280',
            'cancelled': '#ef4444',
            'rescheduled': '#8b5cf6',
            'no_show': '#f97316',
            'rejected': '#dc2626',
        }
        color = status_colors.get(apt.status, '#6b7280')
        
        events.append({
            'id': apt.id,
            'title': f"{apt.patient_name} - {apt.status}",
            'start': f"{apt.appointment_date}T{apt.appointment_time}",
            'color': color,
            'extendedProps': {
                'status': apt.status,
                'patient_name': apt.patient_name,
                'reason': apt.reason[:100] if apt.reason else '',
                'doctor_name': apt.doctor.name,
            }
        })
    
    return JsonResponse(events, safe=False)


# ---------------- AVAILABILITY MANAGEMENT ----------------
@login_required
def manage_availability(request):
    """Manage doctor availability schedule"""
    try:
        profile = request.user.profile
        if profile.role != 'doctor':
            return HttpResponseForbidden("Only doctors can manage availability")
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')
    
    doctor = get_object_or_404(Doctor, name=request.user.username)
    
    # Get or create schedule for each day
    schedules = {}
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for day in days:
        schedule, created = DoctorSchedule.objects.get_or_create(
            doctor=doctor,
            day_of_week=day,
            defaults={
                'start_time': '09:00',
                'end_time': '17:00',
                'is_available': day not in ['saturday', 'sunday'],
                'max_appointments': 8,
                'slot_duration': 30
            }
        )
        schedules[day] = schedule
    
    # Get time blocks
    time_blocks = TimeBlock.objects.filter(
        doctor=doctor,
        end_datetime__gte=timezone.now()
    ).order_by('start_datetime')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_schedule':
            for day in days:
                schedule = schedules[day]
                schedule.start_time = request.POST.get(f'start_{day}', '09:00')
                schedule.end_time = request.POST.get(f'end_{day}', '17:00')
                schedule.is_available = request.POST.get(f'available_{day}') == 'on'
                schedule.max_appointments = int(request.POST.get(f'max_{day}', 8))
                schedule.slot_duration = int(request.POST.get(f'duration_{day}', 30))
                schedule.save()
            messages.success(request, 'Schedule updated successfully!')
            
        elif action == 'add_block':
            start_date = request.POST.get('block_start_date')
            start_time = request.POST.get('block_start_time')
            end_date = request.POST.get('block_end_date')
            end_time = request.POST.get('block_end_time')
            reason = request.POST.get('block_reason', '')
            
            if start_date and start_time and end_date and end_time:
                start_datetime = timezone.make_aware(
                    datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
                )
                end_datetime = timezone.make_aware(
                    datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
                )
                TimeBlock.objects.create(
                    doctor=doctor,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    reason=reason
                )
                messages.success(request, 'Time block added successfully!')
        
        elif action == 'delete_block':
            block_id = request.POST.get('block_id')
            TimeBlock.objects.filter(id=block_id, doctor=doctor).delete()
            messages.success(request, 'Time block removed.')
        
        return redirect('manage_availability')
    
    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'doctor': doctor,
        'schedules': schedules,
        'time_blocks': time_blocks,
        'days': days,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'availability.html', context)


@login_required
def get_available_slots_v2(request):
    """Get available time slots considering doctor schedule"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    doctor_id = request.GET.get('doctor_id')
    date = request.GET.get('date')
    
    if not doctor_id or not date:
        return JsonResponse({'error': 'Doctor ID and date are required'}, status=400)
    
    try:
        doctor = Doctor.objects.get(id=doctor_id)
    except Doctor.DoesNotExist:
        return JsonResponse({'error': 'Doctor not found'}, status=404)
    
    # Get day of week
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        day_of_week = date_obj.strftime('%monday').lower()
        if 'monday' in day_of_week:
            day_of_week = 'monday'
        elif 'tuesday' in day_of_week:
            day_of_week = 'tuesday'
        elif 'wednesday' in day_of_week:
            day_of_week = 'wednesday'
        elif 'thursday' in day_of_week:
            day_of_week = 'thursday'
        elif 'friday' in day_of_week:
            day_of_week = 'friday'
        elif 'saturday' in day_of_week:
            day_of_week = 'saturday'
        else:
            day_of_week = 'sunday'
    except:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Get schedule for this day
    try:
        schedule = DoctorSchedule.objects.get(doctor=doctor, day_of_week=day_of_week)
        if not schedule.is_available:
            return JsonResponse({'slots': [], 'message': 'Doctor not available on this day'})
    except DoctorSchedule.DoesNotExist:
        return JsonResponse({'slots': [], 'message': 'No schedule configured for this day'})
    
    # Get booked appointments
    booked_slots = Appointment.objects.filter(
        doctor=doctor,
        appointment_date=date,
        status__in=['pending', 'approved', 'scheduled']
    ).values_list('appointment_time', flat=True)
    
    # Get time blocks
    date_start = timezone.make_aware(datetime.strptime(f"{date} 00:00", "%Y-%m-%d %H:%M"))
    date_end = timezone.make_aware(datetime.strptime(f"{date} 23:59", "%Y-%m-%d %H:%M"))
    blocks = TimeBlock.objects.filter(
        doctor=doctor,
        start_datetime__lte=date_end,
        end_datetime__gte=date_start
    )
    
    # Generate available slots
    slots = []
    current_time = datetime.combine(datetime.today(), schedule.start_time)
    end_time = datetime.combine(datetime.today(), schedule.end_time)
    
    while current_time + timedelta(minutes=schedule.slot_duration) <= end_time:
        slot_time = current_time.time()
        slot_str = slot_time.strftime('%H:%M')
        
        # Check if booked
        if slot_time not in booked_slots:
            # Check if blocked
            is_blocked = False
            for block in blocks:
                block_start = block.start_datetime.time()
                block_end = block.end_datetime.time()
                if block_start <= slot_time < block_end:
                    is_blocked = True
                    break
            
            if not is_blocked:
                slots.append({
                    'time': slot_str,
                    'display': slot_str
                })
        
        current_time += timedelta(minutes=schedule.slot_duration)
    
    return JsonResponse({'slots': slots})


# ---------------- REMINDERS ----------------
@login_required
def manage_reminders(request):
    """Manage appointment reminders"""
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        messages.error(request, "User profile not found.")
        return redirect('home')
    
    # Get upcoming appointments
    if profile.role == 'doctor':
        doctor = get_object_or_404(Doctor, name=request.user.username)
        appointments = Appointment.objects.filter(
            doctor=doctor,
            appointment_date__gte=timezone.now().date(),
            status__in=['approved', 'scheduled']
        ).order_by('appointment_date', 'appointment_time')
    else:
        appointments = Appointment.objects.filter(
            user=request.user,
            appointment_date__gte=timezone.now().date(),
            status__in=['approved', 'scheduled']
        ).order_by('appointment_date', 'appointment_time')
    
    # Get all reminders for these appointments
    appointment_ids = appointments.values_list('id', flat=True)
    reminders = AppointmentReminder.objects.filter(
        appointment_id__in=appointment_ids
    ).select_related('appointment')
    
    # Group reminders by appointment
    reminders_dict = {}
    for reminder in reminders:
        if reminder.appointment_id not in reminders_dict:
            reminders_dict[reminder.appointment_id] = []
        reminders_dict[reminder.appointment_id].append(reminder)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_reminder':
            appointment_id = request.POST.get('appointment_id')
            reminder_type = request.POST.get('reminder_type', 'email')
            hours_before = float(request.POST.get('hours_before', 24))
            
            appointment = get_object_or_404(Appointment, id=appointment_id)
            
            # Calculate scheduled time
            appointment_datetime = timezone.make_aware(
                datetime.combine(appointment.appointment_date, appointment.appointment_time)
            )
            scheduled_for = appointment_datetime - timedelta(hours=hours_before)
            
            # Create reminder
            AppointmentReminder.objects.create(
                appointment=appointment,
                reminder_type=reminder_type,
                hours_before=hours_before,
                scheduled_for=scheduled_for
            )
            messages.success(request, 'Reminder added successfully!')
        
        elif action == 'delete_reminder':
            reminder_id = request.POST.get('reminder_id')
            AppointmentReminder.objects.filter(id=reminder_id).delete()
            messages.success(request, 'Reminder removed.')
        
        return redirect('manage_reminders')
    
    # Get unread notifications count
    unread_notifications = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'appointments': appointments,
        'reminders_dict': reminders_dict,
        'reminder_choices': AppointmentReminder.REMINDER_TIMES,
        'unread_notifications': unread_notifications,
    }
    return render(request, 'reminders.html', context)


# ---------------- API: SEND REMINDERS (Command) ----------------
def send_pending_reminders():
    """Send all pending reminders that are due"""
    now = timezone.now()
    
    # Get pending reminders that are due
    reminders = AppointmentReminder.objects.filter(
        is_sent=False,
        scheduled_for__lte=now
    ).select_related('appointment')
    
    for reminder in reminders:
        appointment = reminder.appointment
        
        # Send email reminder
        if reminder.reminder_type in ['email', 'both']:
            try:
                subject = f"Appointment Reminder - {appointment.doctor.name}"
                message = f"""
                This is a reminder for your upcoming appointment:
                
                Doctor: {appointment.doctor.name}
                Date: {appointment.appointment_date}
                Time: {appointment.appointment_time}
                
                Please arrive 15 minutes early.
                """
                send_mail(
                    subject=subject,
                    message=message,
                    from_email='noreply@doctorportal.com',
                    recipient_list=[appointment.patient_email],
                    fail_silently=True,
                )
                reminder.is_sent = True
                reminder.sent_at = now
                reminder.sent_via = 'email'
                reminder.save()
            except Exception as e:
                reminder.error_message = str(e)
                reminder.save()
    
    return reminders.count()
