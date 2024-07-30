# leagues/fields.py
from django import forms
import datetime

class TwelveHourTimeField(forms.TimeField):
    def __init__(self, *args, **kwargs):
        kwargs['input_formats'] = ['%I:%M %p', '%H:%M:%S']
        super().__init__(*args, **kwargs)

    def clean(self, value):
        if isinstance(value, str):
            for format in self.input_formats:
                try:
                    return datetime.datetime.strptime(value, format).time()
                except ValueError:
                    continue
            raise forms.ValidationError("Enter a valid time.")
        return super().clean(value)
