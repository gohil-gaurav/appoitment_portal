from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from .models import Profile, Appointment, Notification, StatusHistory, Doctor


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, role='patient')
    else:
        profile, created_profile = Profile.objects.get_or_create(user=instance)
        if created_profile:
            profile.role = 'patient'
            profile.save()


@receiver(post_save, sender=Appointment)
def appointment_created(sender, instance, created, **kwargs):
    """Send notification when a new appointment is created"""
    if created:
        # Use the new Doctor.user relationship instead of name matching
        doctor_user = instance.doctor.user if instance.doctor else None
        
        if doctor_user:
            Notification.objects.create(
                user=doctor_user,
                appointment=instance,
                type='appointment_created',
                title='New Appointment Request',
                message=f'New appointment request from {instance.patient_name} for {instance.appointment_date} at {instance.appointment_time}.'
            )
        
        try:
            send_appointment_email(instance, 'created')
        except Exception as e:
            print(f"Failed to send email: {e}")


@receiver(pre_save, sender=Appointment)
def appointment_status_changed(sender, instance, **kwargs):
    """
    Send email notifications on status change.
    NOTE: StatusHistory and Notification creation is handled in views.py 
    to avoid duplicates. This signal only handles email sending.
    """
    if instance.pk:
        try:
            old_instance = Appointment.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                # Only send email - StatusHistory and Notification are created in views
                try:
                    send_appointment_email(instance, 'status_changed')
                except Exception as e:
                    print(f"Failed to send status change email: {e}")
        except Appointment.DoesNotExist:
            pass


def get_site_url():
    """Get the site URL from settings"""
    return getattr(settings, 'SITE_URL', 'http://localhost:8000')


def send_appointment_email(appointment, email_type):
    """Send email notifications for appointments"""
    if not appointment.patient_email:
        return
    
    site_url = get_site_url()
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@doctorportal.com')
    
    subject = ""
    html_message = ""
    
    if email_type == 'created':
        subject = f"Appointment Request Received - {appointment.doctor.name}"
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Appointment Request Received</h2>
                <p>Dear {appointment.patient_name},</p>
                <p>Your appointment request has been successfully submitted and is awaiting doctor approval.</p>
                
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin: 0 0 10px 0; color: #374151;">Appointment Details:</h3>
                    <p><strong>Doctor:</strong> {appointment.doctor.name}</p>
                    <p><strong>Specialization:</strong> {appointment.doctor.specialization}</p>
                    <p><strong>Date:</strong> {appointment.appointment_date}</p>
                    <p><strong>Time:</strong> {appointment.appointment_time}</p>
                    <p><strong>Status:</strong> {appointment.get_status_display()}</p>
                    {f'<p><strong>Reason:</strong> {appointment.reason}</p>' if appointment.reason else ''}
                </div>
                
                <p>You will receive another email once the doctor reviews and approves your appointment request.</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{site_url}/patient/dashboard/" style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">View Dashboard</a>
                </div>
                
                <p>Best regards,<br>Doctor Appointment Portal Team</p>
            </div>
        </body>
        </html>
        """
    
    elif email_type == 'status_changed':
        status_messages = {
            'approved': 'approved and confirmed',
            'scheduled': 'scheduled for your selected time',
            'completed': 'completed successfully',
            'cancelled': 'cancelled',
            'rescheduled': 'rescheduled to a new time',
            'no_show': 'marked as no-show',
            'rejected': 'rejected'
        }
        
        message = status_messages.get(appointment.status, f'changed to {appointment.status}')
        
        subject = f"Appointment {message.title()} - {appointment.doctor.name}"
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #059669;">Appointment Status Update</h2>
                <p>Dear {appointment.patient_name},</p>
                <p>Your appointment status has been updated: <strong>{message}</strong>.</p>
                
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin: 0 0 10px 0; color: #374151;">Appointment Details:</h3>
                    <p><strong>Doctor:</strong> {appointment.doctor.name}</p>
                    <p><strong>Specialization:</strong> {appointment.doctor.specialization}</p>
                    <p><strong>Date:</strong> {appointment.appointment_date}</p>
                    <p><strong>Time:</strong> {appointment.appointment_time}</p>
                    <p><strong>Current Status:</strong> {appointment.get_status_display()}</p>
                    {f'<p><strong>Cancellation Reason:</strong> {appointment.cancellation_reason}</p>' if appointment.cancellation_reason else ''}
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{site_url}/patient/dashboard/" style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">View Dashboard</a>
                </div>
                
                <p>Best regards,<br>Doctor Appointment Portal Team</p>
            </div>
        </body>
        </html>
        """
    
    if subject and html_message:
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=from_email,
                recipient_list=[appointment.patient_email],
                html_message=html_message,
                fail_silently=False,
            )
        except Exception as e:
            print(f"Failed to send email: {e}")


@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """Send email for important notifications"""
    if created and instance.user.profile.email_notifications:
        important_types = ['appointment_created', 'status_changed']
        
        if instance.type in important_types and instance.user.email:
            try:
                subject = f"Appointment Update - {instance.title}"
                message = f"""
                {instance.title}
                
                {instance.message}
                
                Please log in to your dashboard for more details.
                """
                
                send_mail(
                    subject=subject,
                    message=message,
                    from_email='noreply@doctorportal.com',
                    recipient_list=[instance.user.email],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send notification email: {e}")
