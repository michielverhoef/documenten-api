# Generated by Django 2.2.2 on 2019-07-01 14:17

from django.db import migrations, models
import vng_api_common.validators


class Migration(migrations.Migration):

    dependencies = [("datamodel", "0040_reset_sequences")]

    operations = [
        migrations.AlterField(
            model_name="enkelvoudiginformatieobject",
            name="identificatie",
            field=models.CharField(
                default="",
                help_text="Een binnen een gegeven context ondubbelzinnige referentie naar het INFORMATIEOBJECT.",
                max_length=40,
                validators=[vng_api_common.validators.AlphanumericExcludingDiacritic()],
            ),
        )
    ]
