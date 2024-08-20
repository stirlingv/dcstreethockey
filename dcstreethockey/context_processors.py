# context_processors.py
from leagues.models import HomePage  # Adjust the import to your specific model location

def homepage_logo(request):
    try:
        homepage = HomePage.objects.first()
        return {'homepage_logo': homepage.logo if homepage else None}
    except HomePage.DoesNotExist:
        return {'homepage_logo': None}
