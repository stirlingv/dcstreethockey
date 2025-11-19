# leagues/forms.py
from django import forms
from .models import MatchUp
from .widgets import Time12HourWidget
from .fields import TwelveHourTimeField


class MatchUpForm(forms.ModelForm):
    time = TwelveHourTimeField(widget=Time12HourWidget(attrs={"class": "vTimeField"}))

    class Meta:
        model = MatchUp
        fields = "__all__"
