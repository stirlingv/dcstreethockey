# leagues/widgets.py
from django import forms
import datetime

class Time12HourWidget(forms.TimeInput):
    def __init__(self, attrs=None):
        super().__init__(attrs, format='%I:%M %p')

    def render(self, name, value, attrs=None, renderer=None):
        if isinstance(value, str):
            try:
                value = datetime.datetime.strptime(value, '%H:%M:%S').time()  # Handle value from the database
            except ValueError:
                try:
                    value = datetime.datetime.strptime(value, '%I:%M %p').time()
                except ValueError:
                    pass
        elif value is not None:
            value = value.strftime('%I:%M %p')
        return super().render(name, value, attrs, renderer)
    
    def format_value(self, value):
        if isinstance(value, str):
            try:
                value = datetime.datetime.strptime(value, '%H:%M:%S').time()  # Handle value from the database
            except ValueError:
                try:
                    value = datetime.datetime.strptime(value, '%I:%M %p').time()
                except ValueError:
                    return value
        if value is None:
            return ''
        return value.strftime('%I:%M %p')
