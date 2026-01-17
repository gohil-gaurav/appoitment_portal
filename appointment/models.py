from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings


class Doctor(models.Model):
    # Link to User account (proper relationship instead of name matching)
    user = models.OneToOneField(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='doctor_profile'
    )
    name = models.CharField(max_length=100)
    specialization = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    available_from = models.TimeField(null=True, blank=True)
    available_to = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    experience_years = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    affiliation = models.CharField(max_length=150, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    
    # Review & Rating fields (denormalized for performance)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    def update_rating(self):
        """Update the average rating and total reviews count"""
        from django.db.models import Avg
        reviews = self.reviews.filter(is_approved=True)
        avg = reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
        self.average_rating = round(avg, 2) if avg else 0
        self.total_reviews = reviews.count()
        self.save(update_fields=['average_rating', 'total_reviews'])

    def get_rating_display(self):
        """Return a formatted rating string with stars"""
        return f"{self.average_rating} ({self.total_reviews} reviews)"

    class Meta:
        ordering = ['name']


class Appointment(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
        ('rescheduled', 'Rescheduled'),
        ('rejected', 'Rejected'),
    )
    
    PRIORITY_CHOICES = (
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    )

    # Patient Information
    patient_name = models.CharField(max_length=100)
    patient_email = models.EmailField()
    patient_phone = models.CharField(max_length=15, blank=True)
    
    # Doctor and Scheduling
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    
    # Status and Tracking
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='pending'
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='normal'
    )
    
    # Additional Information
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # User (if authenticated)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.patient_name} - {self.doctor.name} ({self.status})"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['doctor', 'appointment_date']),
            models.Index(fields=['user', 'status']),
        ]

    def is_upcoming(self):
        """Check if appointment is in the future"""
        now = timezone.now()
        appointment_datetime = timezone.make_aware(
            timezone.datetime.combine(self.appointment_date, self.appointment_time)
        )
        return appointment_datetime > now

    def is_past(self):
        """Check if appointment is in the past"""
        return not self.is_upcoming()

    def can_be_cancelled(self):
        """Check if appointment can be cancelled"""
        return self.status in ['pending', 'approved', 'scheduled']

    def can_be_rescheduled(self):
        """Check if appointment can be rescheduled"""
        return self.status in ['pending', 'approved', 'scheduled']


class Review(models.Model):
    """Review and rating system for doctors"""
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='reviews')
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='doctor_reviews')
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, null=True, blank=True, related_name='reviews')
    
    # Rating: 1-5 stars
    rating = models.PositiveIntegerField(
        choices=[(i, f"{i} Star{'s' if i > 1 else ''}") for i in range(1, 6)]
    )
    
    # Review content
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField()
    
    # Review management
    is_approved = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    
    # Helpfulness voting
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.username}'s review of {self.doctor.name}"

    class Meta:
        ordering = ['-created_at']
        unique_together = ('doctor', 'patient', 'appointment')  # One review per appointment

    def get_star_rating(self):
        """Return HTML stars for display"""
        stars = ''
        for i in range(1, 6):
            if i <= self.rating:
                stars += '<i class="fas fa-star text-yellow-400"></i>'
            else:
                stars += '<i class="far fa-star text-gray-400"></i>'
        return stars


class AppointmentReminder(models.Model):
    """Manage appointment reminders"""
    REMINDER_TYPES = (
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('both', 'Email & SMS'),
    )

    REMINDER_TIMES = (
        (24, '1 day before'),
        (2, '2 hours before'),
        (1, '1 hour before'),
        (0.5, '30 minutes before'),
    )

    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name='reminders')
    reminder_type = models.CharField(max_length=10, choices=REMINDER_TYPES, default='email')
    hours_before = models.FloatField(choices=REMINDER_TIMES, default=24)
    
    # Reminder status
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_via = models.CharField(max_length=10, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    
    # Scheduling
    scheduled_for = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reminder for {self.appointment} - {self.get_hours_before_display()}"

    class Meta:
        ordering = ['scheduled_for']

    def get_hours_before_display(self):
        """Get human-readable reminder time"""
        for hours, label in self.REMINDER_TIMES:
            if hours == self.hours_before:
                return label
        return f"{self.hours_before} hours before"


class StatusHistory(models.Model):
    """Track all status changes for appointments"""
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(max_length=15, null=True, blank=True)
    new_status = models.CharField(max_length=15)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.appointment} - {self.old_status} → {self.new_status}"

    class Meta:
        ordering = ['-changed_at']


class Notification(models.Model):
    """Manage notifications for users"""
    NOTIFICATION_TYPES = (
        ('appointment_created', 'Appointment Created'),
        ('status_changed', 'Status Changed'),
        ('appointment_reminder', 'Appointment Reminder'),
        ('appointment_cancelled', 'Appointment Cancelled'),
        ('appointment_rescheduled', 'Appointment Rescheduled'),
        ('system', 'System Notification'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=25, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.title}"

    class Meta:
        ordering = ['-created_at']


class DoctorSchedule(models.Model):
    """Manage doctor availability and schedules"""
    DAYS_OF_WEEK = (
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    )

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='schedules')
    day_of_week = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True)
    max_appointments = models.PositiveIntegerField(default=10)
    slot_duration = models.PositiveIntegerField(default=30, help_text="Duration in minutes")

    def __str__(self):
        return f"{self.doctor.name} - {self.day_of_week}"

    class Meta:
        unique_together = ('doctor', 'day_of_week')

    def get_time_slots(self):
        """Generate available time slots for this day"""
        from datetime import datetime, timedelta
        slots = []
        current = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        
        while current + timedelta(minutes=self.slot_duration) <= end:
            slots.append(current.time())
            current += timedelta(minutes=self.slot_duration)
        
        return slots


class TimeBlock(models.Model):
    """Block specific time slots for doctors (vacations, meetings, etc.)"""
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='time_blocks')
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)
    is_recurring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.doctor.name} - {self.start_datetime.date()} blocked"

    class Meta:
        ordering = ['start_datetime']


class PatientNotes(models.Model):
    """Store patient medical history and notes"""
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='medical_notes')
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, null=True, blank=True)
    note_type = models.CharField(max_length=20, choices=(
        ('medical_history', 'Medical History'),
        ('diagnosis', 'Diagnosis'),
        ('prescription', 'Prescription'),
        ('treatment', 'Treatment'),
        ('general', 'General Note'),
    ))
    title = models.CharField(max_length=200)
    content = models.TextField()
    is_confidential = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.username} - {self.title}"

    class Meta:
        ordering = ['-created_at']


class Profile(models.Model):
    ROLE_CHOICES = (
        ('doctor', 'Doctor'),
        ('patient', 'Patient'),
        ('admin', 'Admin'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    specialization = models.CharField(max_length=100, blank=True)
    
    # Enhanced Profile Fields
    phone = models.CharField(max_length=15, blank=True, default='')
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True, default='')
    # Use FileField instead of ImageField to avoid the Pillow dependency while
    # still allowing an optional uploaded file for the profile picture.
    profile_picture = models.FileField(upload_to='profile_pics/', null=True, blank=True)
    
    # Notification Preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    
    # Privacy Settings
    is_public = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"

    def get_age(self):
        """Calculate age from date of birth"""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None

    class Meta:
        ordering = ['user__username']

