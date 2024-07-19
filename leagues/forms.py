# leagues/forms.py
from django import forms
from .models import MatchUp
from .widgets import Time12HourWidget

class MatchUpForm(forms.ModelForm):
    class Meta:
        model = MatchUp
        fields = '__all__'
        widgets = {
            'time': Time12HourWidget(attrs={'class': 'vTimeField'}),
        }
