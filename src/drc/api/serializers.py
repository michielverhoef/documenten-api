"""
Serializers of the Document Registratie Component REST API
"""
import uuid

from django.conf import settings
from django.utils.encoding import force_text
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

from drf_extra_fields.fields import Base64FileField
from privates.storages import PrivateMediaFileSystemStorage
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.settings import api_settings
from vng_api_common.constants import ObjectTypes
from vng_api_common.models import APICredential
from vng_api_common.serializers import GegevensGroepSerializer
from vng_api_common.validators import IsImmutableValidator, URLValidator

from drc.datamodel.models import (
    EnkelvoudigInformatieObject, Gebruiksrechten, ObjectInformatieObject
)

from .auth import get_zrc_auth, get_ztc_auth
from .validators import (
    InformatieObjectUniqueValidator, ObjectInformatieObjectValidator,
    StatusValidator
)


class AnyFileType:
    def __contains__(self, item):
        return True


class AnyBase64File(Base64FileField):
    ALLOWED_TYPES = AnyFileType()

    def __init__(self, view_name: str = None, *args, **kwargs):
        self.view_name = view_name
        super().__init__(*args, **kwargs)

    def get_file_extension(self, filename, decoded_file):
        return "bin"

    def to_representation(self, file):
        is_private_storage = isinstance(file.storage, PrivateMediaFileSystemStorage)

        if not is_private_storage or self.represent_in_base64:
            return super().to_representation(file)

        assert self.view_name, "You must pass the `view_name` kwarg for private media fields"

        model_instance = file.instance
        request = self.context.get('request')

        url_field = self.parent.fields["url"]
        lookup_field = url_field.lookup_field
        kwargs = {lookup_field: getattr(model_instance, lookup_field)}
        return reverse(self.view_name, kwargs=kwargs, request=request)


class IntegriteitSerializer(GegevensGroepSerializer):
    class Meta:
        model = EnkelvoudigInformatieObject
        gegevensgroep = 'integriteit'


class OndertekeningSerializer(GegevensGroepSerializer):
    class Meta:
        model = EnkelvoudigInformatieObject
        gegevensgroep = 'ondertekening'


class EnkelvoudigInformatieObjectSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the EnkelvoudigInformatieObject model
    """
    inhoud = AnyBase64File(view_name="enkelvoudiginformatieobject-download")
    bestandsomvang = serializers.IntegerField(
        source='inhoud.size', read_only=True,
        min_value=0
    )
    integriteit = IntegriteitSerializer(
        label=_("integriteit"), allow_null=True, required=False,
        help_text=_("Uitdrukking van mate van volledigheid en onbeschadigd zijn van digitaal bestand.")
    )
    # TODO: validator!
    ondertekening = OndertekeningSerializer(
        label=_("ondertekening"), allow_null=True, required=False,
        help_text=_("Aanduiding van de rechtskracht van een informatieobject. Mag niet van een waarde "
                    "zijn voorzien als de `status` de waarde 'in bewerking' of 'ter vaststelling' heeft.")
    )

    class Meta:
        model = EnkelvoudigInformatieObject
        fields = (
            'url',
            'identificatie',
            'bronorganisatie',
            'creatiedatum',
            'titel',
            'vertrouwelijkheidaanduiding',
            'auteur',
            'status',
            'formaat',
            'taal',
            'bestandsnaam',
            'inhoud',
            'bestandsomvang',
            'link',
            'beschrijving',
            'ontvangstdatum',
            'verzenddatum',
            'indicatie_gebruiksrecht',
            'ondertekening',
            'integriteit',
            'informatieobjecttype',  # van-relatie
            'lock'
        )
        extra_kwargs = {
            'url': {
                'lookup_field': 'uuid',
            },
            'informatieobjecttype': {
                'validators': [URLValidator(get_auth=get_ztc_auth)],
            },
            'lock':  {
                'write_only': True,
                'help_text': _("Lock must be provided during updating the document (PATCH, PUT), "
                               "not while creating it")
            }
        }
        validators = [StatusValidator()]

    def _get_informatieobjecttype(self, informatieobjecttype_url: str) -> dict:
        if not hasattr(self, 'informatieobjecttype'):
            # dynamic so that it can be mocked in tests easily
            Client = import_string(settings.ZDS_CLIENT_CLASS)
            client = Client.from_url(informatieobjecttype_url)
            client.auth = APICredential.get_auth(
                informatieobjecttype_url,
                scopes=['zds.scopes.zaaktypes.lezen']
            )
            self._informatieobjecttype = client.request(informatieobjecttype_url, 'informatieobjecttype')
        return self._informatieobjecttype

    def validate_indicatie_gebruiksrecht(self, indicatie):
        if self.instance and not indicatie and self.instance.gebruiksrechten_set.exists():
            raise serializers.ValidationError(
                _("De indicatie kan niet weggehaald worden of ongespecifieerd "
                  "zijn als er Gebruiksrechten gedefinieerd zijn."),
                code='existing-gebruiksrechten'
            )
        # create: not self.instance or update: usage_rights exists
        elif indicatie and (not self.instance or not self.instance.gebruiksrechten_set.exists()):
            raise serializers.ValidationError(
                _("De indicatie moet op 'ja' gezet worden door `gebruiksrechten` "
                  "aan te maken, dit kan niet direct op deze resource."),
                code='missing-gebruiksrechten'
            )
        return indicatie

    def validate(self, attrs):
        valid_attrs = super().validate(attrs)

        lock = valid_attrs.get('lock', '')
        # update
        if self.instance:
            if not self.instance.lock:
                raise serializers.ValidationError(
                    _("Unlocked document can't be modified"),
                    code='unlocked'
                )
            if lock != self.instance.lock:
                raise serializers.ValidationError(
                    _("Lock id is not correct"),
                    code='incorrect-lock-id'
                )
        # create
        else:
            if lock:
                raise serializers.ValidationError(
                    _("A locked document can't be created"),
                    code='lock-in-create'
                )
        return valid_attrs

    def create(self, validated_data):
        """
        Handle nested writes.
        """
        integriteit = validated_data.pop('integriteit', None)
        ondertekening = validated_data.pop('ondertekening', None)
        # add vertrouwelijkheidaanduiding
        if 'vertrouwelijkheidaanduiding' not in validated_data:
            informatieobjecttype = self._get_informatieobjecttype(validated_data['informatieobjecttype'])
            validated_data['vertrouwelijkheidaanduiding'] = informatieobjecttype['vertrouwelijkheidaanduiding']

        eio = super().create(validated_data)
        eio.integriteit = integriteit
        eio.ondertekening = ondertekening
        eio.save()
        return eio

    def update(self, instance, validated_data):
        """
        Handle nested writes.
        """
        instance.integriteit = validated_data.pop('integriteit', None)
        instance.ondertekening = validated_data.pop('ondertekening', None)
        return super().update(instance, validated_data)


class LockEnkelvoudigInformatieObjectSerializer(serializers.ModelSerializer):
    """
    Serializer for the lock action of EnkelvoudigInformatieObject model
    """
    class Meta:
        model = EnkelvoudigInformatieObject
        fields = ('lock', )
        extra_kwargs = {
            'lock': {
                'read_only': True,
            }
        }

    def validate(self, attrs):
        valid_attrs = super().validate(attrs)

        if self.instance.lock:
            raise serializers.ValidationError(
                _("The document is already locked"),
                code='existing-lock'
            )
        return valid_attrs

    def save(self, **kwargs):
        self.instance.lock = uuid.uuid4().hex
        self.instance.save()

        return self.instance


class UnlockEnkelvoudigInformatieObjectSerializer(serializers.ModelSerializer):
    """
    Serializer for the unlock action of EnkelvoudigInformatieObject model
    """
    class Meta:
        model = EnkelvoudigInformatieObject
        fields = ('lock', )
        extra_kwargs = {
            'lock': {
                'required': False,
                'write_only': True,
            }
        }

    def validate(self, attrs):
        valid_attrs = super().validate(attrs)
        force_unlock = self.context.get('force_unlock', False)

        if force_unlock:
            return valid_attrs

        lock = valid_attrs.get('lock', '')
        if lock != self.instance.lock:
            raise serializers.ValidationError(
                _("Lock id is not correct"),
                code='incorrect-lock-id'
            )
        return valid_attrs

    def save(self, **kwargs):
        self.instance.lock = ''
        self.instance.save()
        return self.instance


class ObjectInformatieObjectSerializer(serializers.HyperlinkedModelSerializer):
    # TODO: valideer dat ObjectInformatieObject.informatieobjecttype hoort
    # bij zaak.zaaktype
    class Meta:
        model = ObjectInformatieObject
        fields = (
            'url',
            'informatieobject',
            'object',
            'object_type',
        )
        extra_kwargs = {
            'url': {
                'lookup_field': 'uuid',
            },
            'informatieobject': {
                'lookup_field': 'uuid',
            },
            'object': {
                'validators': [
                    URLValidator(get_auth=get_zrc_auth, headers={'Accept-Crs': 'EPSG:4326'}),
                    IsImmutableValidator(),
                ],
            },
            'object_type': {
                'validators': [IsImmutableValidator()]
            }
        }
        validators = [ObjectInformatieObjectValidator(), InformatieObjectUniqueValidator('object', 'informatieobject')]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not hasattr(self, 'initial_data'):
            return


class GebruiksrechtenSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Gebruiksrechten
        fields = (
            'url',
            'informatieobject',
            'startdatum',
            'einddatum',
            'omschrijving_voorwaarden'
        )
        extra_kwargs = {
            'url': {
                'lookup_field': 'uuid',
            },
            'informatieobject': {
                'lookup_field': 'uuid',
                'validators': [IsImmutableValidator()],
            },
        }
