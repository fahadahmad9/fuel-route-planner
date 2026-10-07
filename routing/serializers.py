from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=100,
        trim_whitespace=True,
    )
    finish = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=100,
        trim_whitespace=True,
    )
