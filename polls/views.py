from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader

from .models import Question

# def index(request):
#     latest_question_list = Question.objects.order_by('-pub_date')[:5]
#     context = {'latest_question_list': latest_question_list}
#     return render(request, 'polls/index.html', context)

# def index(request):
#     latest_question_list = Question.objects.order_by('-pub_date')[:5]
#     template = loader.get_template('polls/index.html')
#     context = {
#         'latest_question_list': latest_question_list,
#     }
#     return HttpResponse(template.render(context, request))

def index(request):
    latest_question_list = Question.objects.order_by('-pub_date')[:5]
    ques_list = [q.question_text for q in latest_question_list]
    return render(request, "polls/index.html", context={"latest_question_list": ques_list})
    #return HttpResponse(output)

# def index(request):
# 	#return HttpResponse("DC Street Hockey poll index.")
# 	return render(request, "polls/index.html", context={"latest_question_list": ["question1", "question2"]})

# Create your views here.
def detail(request, question_id):
    return HttpResponse("You're looking at question %s." % question_id)

def results(request, question_id):
    response = "You're looking at the results of question %s."
    return HttpResponse(response % question_id)

def vote(request, question_id):
    return HttpResponse("You're voting on question %s." % question_id)