from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import RegistrationForm


def register(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect('plan_list')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('plan_list')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})
