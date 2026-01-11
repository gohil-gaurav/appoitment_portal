from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from datetime import datetime, timedelta
from appointment.models import AppointmentReminder, Appointment


class Command(BaseCommand):
    help = 'Send pending appointment reminders'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Get pending reminders that are due
        reminders = AppointmentReminder.objects.filter(
            is_sent=False,
            scheduled_for__lte=now
        ).select_related('appointment', 'appointment__doctor')
        
        sent_count = 0
        
        for reminder in reminders:
            appointment = reminder.appointment
            
            # Send email reminder
            if reminder.reminder_type in ['email', 'both']:
                try:
                    subject = f"Appointment Reminder - {appointment.doctor.name}"
                    message = f"""
Dear {appointment.patient_name},

This is a reminder for your upcoming appointment:

Doctor: {appointment.doctor.name}
Specialization: {appointment.doctor.specialization}
Date: {appointment.appointment_date}
Time: {appointment.appointment_time}

Please arrive 15 minutes early and bring any relevant medical documents.

If you need to reschedule, please do so at least 24 hours in advance.

Best regards,
Doctor Appointment Portal
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
                    sent_count += 1
                    
                    self.stdout.write(
                        self.style.SUCCESS(f'Sent reminder for appointment {appointment.id}')
                    )
                except Exception as e:
                    reminder.error_message = str(e)
                    reminder.save()
                    self.stdout.write(
                        self.style.ERROR(f'Failed to send reminder for appointment {appointment.id}: {e}')
                    )
        
        self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} reminders'))

