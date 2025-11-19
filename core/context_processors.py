from django.templatetags.static import static


def jersey_path(request):
    return {"jersey_path": static("img/emojis/")}
