from django import forms
from .models import LeadApplication, Course
import re

class LeadApplicationForm(forms.ModelForm):
    course = forms.ModelChoiceField(
        queryset=Course.objects.filter(is_active=True),
        required=False,
        empty_label="Выберите интересующий курс...",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'course_select'})
    )

    class Meta:
        model = LeadApplication
        fields = ['name', 'phone', 'course', 'message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Как к вам обращаться? (например, Алия)',
                'required': True,
                'id': 'client_name'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+7 (708) 116-02-65',
                'required': True,
                'id': 'client_phone'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Укажите удобное время для звонка, возраст студента или филиал...',
                'id': 'client_message'
            }),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        # Очищаем от скобок, пробелов и дефисов
        clean_digits = re.sub(r'\D', '', phone)
        if len(clean_digits) < 10:
            raise forms.ValidationError("Пожалуйста, введите корректный номер телефона (например: +7 708 116 02 65)")
        return phone
