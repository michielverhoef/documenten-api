# Generated by Django 2.0.6 on 2018-10-25 13:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("datamodel", "0019_auto_20181024_1313")]

    operations = [
        migrations.AddField(
            model_name="objectinformatieobject",
            name="aard_relatie",
            field=models.CharField(
                choices=[
                    ("hoort_bij", "Hoort bij, omgekeerd: kent"),
                    ("legt_vast", "Legt vast, omgekeerd: kan vastgelegd zijn als"),
                ],
                default="hoort_bij",
                max_length=20,
                verbose_name="aard relatie",
            ),
            preserve_default=False,
        )
    ]
