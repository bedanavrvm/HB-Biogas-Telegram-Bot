from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('core', '0166_compact_complaint_category_descriptions')]

    operations = [
        migrations.RemoveIndex(model_name='parsedmessage', name='core_parsed_message_8b884d_idx'),
        migrations.RemoveIndex(model_name='orderapprovalupdate', name='core_ordera_telegra_f2187c_idx'),
        migrations.RemoveIndex(model_name='mediaattachment', name='core_mediaa_telegra_027c57_idx'),
        migrations.RemoveIndex(model_name='spincreditrequest', name='core_spincr_source__df5fb4_idx'),
        migrations.RemoveIndex(model_name='livesheetrecordchange', name='core_livesh_record__b1b9dc_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_duplica_044aac_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_hbg_con_e81a9a_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_hb_sale_3dbb1e_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_jbl_vis_3161c5_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_credit__5f4c46_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_custome_60ba33_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_final_d_c85c3c_idx'),
        migrations.RemoveIndex(model_name='jawabufarmermaster', name='core_jawabu_order_n_c72bdf_idx'),
        migrations.RemoveIndex(model_name='jawabufarmeruploadbatch', name='core_jawabu_telegra_1d22d8_idx'),
        migrations.RemoveIndex(model_name='parsedinvoice', name='core_parsed_invoice_d34219_idx'),
    ]
