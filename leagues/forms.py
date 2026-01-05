# leagues/forms.py
from django import forms
from dal import autocomplete
from .models import MatchUp
from .widgets import Time12HourWidget
from .fields import TwelveHourTimeField


class MatchUpForm(forms.ModelForm):
    time = TwelveHourTimeField(widget=Time12HourWidget(attrs={"class": "vTimeField"}))

    class Meta:
        model = MatchUp
        fields = "__all__"
        widgets = {
            "away_goalie": autocomplete.ModelSelect2(url="goalie-autocomplete"),
            "home_goalie": autocomplete.ModelSelect2(url="goalie-autocomplete"),
        }
