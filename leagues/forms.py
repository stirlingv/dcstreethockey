# leagues/forms.py
from django import forms
from dal import autocomplete
from .models import MatchUp, Team_Stat
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


class TeamStatForm(forms.ModelForm):
    class Meta:
        model = Team_Stat
        fields = ["win", "otw", "loss", "otl", "tie", "goals_for", "goals_against"]
        labels = {
            "win": "W",
            "otw": "OTW",
            "loss": "L",
            "otl": "OTL",
            "tie": "T",
            "goals_for": "GF",
            "goals_against": "GA",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"style": "width:55px;text-align:center;", "min": "0"}
            )


class PlayerPhotoUploadForm(forms.Form):
    photo = forms.ImageField(
        label="Photo",
        help_text="JPG or PNG. The admin will review it before it goes live.",
    )
    submitter_email = forms.EmailField(
        label="Your email (optional)",
        required=False,
        help_text="Only used if the admin needs to follow up.",
    )
    submitter_note = forms.CharField(
        label="Note to admin (optional)",
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "e.g. cropped from team photo, Fall 2024"}
        ),
    )
