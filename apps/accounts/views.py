from django.shortcuts import render

from rest_framework import mixins, viewsets, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny

from apps.accounts.serializers import RegisterSerializer, LoginSerializer, UserSerializer
from apps.accounts.models import User

# Create your views here.
#UserViewSet: A viewset that allows listing, retrieving, updating, and deleting user instances. Only accessible by admin users.
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]


#RegisterView: A view for handling user registration requests. Only accessible by any user.
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    #Overriding create() to handle user registration. It validates the incoming data, creates a new user instance, generates JWT tokens for the user, and returns a response with the created user's data and tokens.
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
    
        return Response(
            {
                "message": "Registration successful.",
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )
    

#LoginView: A view for handling user login requests. Only accessible by any user.
class LoginView(APIView):
    permission_classes = [AllowAny]
    
    #Overriding post() to handle user login. It validates the incoming data, authenticates the user, generates JWT tokens for the authenticated user, and returns a response with the user's data and tokens.
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
    
    
#UserView: A view for retrieving the currently authenticated user's information. Only accessible by authenticated users.
class UserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user