"""Reviewed blank supporting sources; drafts only, never product auto-assignments.

Native legal roles absent from the current signing policy remain explicit repair
tasks. These seeds do not turn a witness into an advocate or an applicant into
the collateral owner. Occurrences are mapping references, not PDF coordinates.
"""
from copy import deepcopy

from origination.services.origination_main_laf_seeds import (
    MainLafDefinition, _field, _signer, _generic,
)
from origination.services.origination_value_contracts import reviewed_contract


def entered(key, label, type='text', *, subject='application', local=False, required=False, page=1, printed=None):
    spec = _field(key, label, type, 'document_details', required=required,
                  sensitivity='financial' if type == 'money' else 'pii')
    spec['value_contract'] = {**reviewed_contract(spec), 'subject': subject,
                             'scope': 'document' if local else 'application'}
    spec['occurrences'] = [{'page': page, 'label': printed or label}]
    return spec


def generated(key, label, *, pages=(1,), printed=None):
    from origination.services.origination_commercial_terms import FIELD_SPECS
    type = next((spec[2] for spec in FIELD_SPECS if spec[0] == key), 'text')
    spec = _field(key, label, type, 'document_details', source='system')
    spec['value_contract'] = reviewed_contract(spec)
    spec['occurrences'] = [{'page': page, 'label': printed or label} for page in pages]
    return spec


def reuse(key, *, page=1, printed=None):
    spec = deepcopy(_generic(key, section='document_details')[0])
    spec['value_contract'] = reviewed_contract(spec)
    spec['occurrences'] = [{'page': page, 'label': printed or spec['label']}]
    return spec


IDENTITY = (
    generated('borrower_full_name', 'Applicant name'), reuse('applicant_id_number'),
    reuse('applicant_phone'), reuse('applicant_postal_address'),
)
VEHICLE = tuple(entered('vehicle_' + key, label, type, subject='vehicle', page=3 if key in {
    'description', 'type', 'registration_number', 'year_manufactured', 'engine_number', 'make'} else 4)
    for key, label, type in [
        ('description', 'Vehicle description', 'text'), ('type', 'Vehicle type', 'text'),
        ('registration_number', 'Vehicle registration', 'text'), ('year_manufactured', 'Year of manufacture', 'number'),
        ('engine_number', 'Engine number', 'text'), ('make', 'Vehicle make', 'text'),
        ('model', 'Vehicle model', 'text'), ('chassis_number', 'Chassis number', 'text'), ('colour', 'Vehicle colour', 'text'),
        ('registered_owner_name', 'Registered owner', 'text'),
    ])
PARTY_IDENTITY = {'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone', 'national_id': 'guarantor_1_id_number'}
SECTIONS = (('document_details', 'Document details', ''),)


DEFINITIONS = (
    MainLafDefinition('guarantee', 'SUPPORT LAF- GUARANTOR FORM.pdf',
        '463ae42ecc15e866f7c7edbd9052362817ed5b0e01bdf584fe8691c2c67c5901', 622484, 1,
        'jawabu_guarantee', 'Guarantee and undertaking', None, SECTIONS,
        (reuse('guarantor_1_name'), reuse('guarantor_1_id_number'), reuse('guarantor_1_phone'),
         entered('guarantor_1_postal_address', 'Guarantor postal address', subject='guarantor_1'),
         entered('guarantor_1_town', 'Guarantor town', subject='guarantor_1'),
         entered('guarantor_1_email', 'Guarantor email', subject='guarantor_1'),
         generated('borrower_full_name', 'Borrower name', pages=(1, 1, 1)), reuse('applicant_id_number'),
         entered('guaranteed_amount', 'Amount guaranteed', 'money', subject='loan', local=True,
                 printed='Loan amount advanced / sum guaranteed'),
         entered('guarantee_referenced_agreement_date', 'Referenced agreement date', 'date', subject='document', local=True),
         entered('witness_name', 'Witness name', subject='document', local=True),
         entered('witness_phone', 'Witness phone', 'phone', subject='document', local=True),
         entered('witness_national_id', 'Witness ID', 'national_id', subject='document', local=True)),
        (_signer('guarantor_1', 'Guarantor 1', identity_fields=PARTY_IDENTITY),
         _signer('witness', 'Witness', identity_fields={'name':'witness_name', 'phone':'witness_phone', 'national_id':'witness_national_id'})),
        review_notes=('The guaranteed obligation is not the requested or disbursed amount.',
                      'Witness identity is signing evidence; witness phone/ID are not printed blanks.'),
        document_role='supporting', required_signer_roles=('guarantor_1','witness')),
    MainLafDefinition('home_visit', 'SUPPORT LAF- HOME VISIT FORM.pdf',
        '767b5bfc09f3789aa6b53b7817be0f489fedc95835e7b2a161efea9d00f4cd0c', 408129, 1,
        'jawabu_home_visit', 'Home visit', None, SECTIONS,
        (entered('asset_owner_name', 'Asset owner name', subject='asset_owner', printed='Assets belong to / I confirm owner'),
         entered('asset_owner_national_id', 'Asset owner ID', 'national_id', subject='asset_owner'),
         generated('application_date', 'Loan application date', pages=(1,1)),
         generated('secured_assets_total', 'Estimated value total'),
         _field('secured_assets', 'Home visit assets', 'repeating_group', 'document_details', structure={
             'min_items': 0, 'max_items': 10, 'columns': [
                 {'key':'description', 'label':'Item', 'type':'text', 'required':True},
                 {'key':'estimated_value', 'label':'Estimated value', 'type':'money', 'required':True}]}, width='full'),
         generated('loan_officer_name', 'BRO name'), generated('home_visit_completed_date', 'Visit date')),
        (_signer('officer', 'Visit officer'),), review_notes=(
            'Owner confirmation needs its own signer; never assume the owner is the borrower.',
            'A preview date is not evidence that a visit occurred. Table capacity must be visually confirmed.'),
        document_role='supporting', required_signer_roles=('asset_owner','officer')),
    MainLafDefinition('preappraisal', 'SUPPORT LAF- PRE-APPRAISAL FORM.pdf',
        'e8652cabd9bde1e5bb995d48c38c04460164fd928f51e8630ac1e742082c117e', 291667, 1,
        'jawabu_preappraisal', 'Pre-appraisal', None, SECTIONS,
        (*IDENTITY, reuse('applicant_other_phone'), reuse('applicant_email'), reuse('applicant_residence_address'),
         reuse('business_type'), reuse('business_location'), reuse('loan_purpose'), reuse('loan_amount'),
         entered('business_started_on', 'Business started on', 'date', subject='business'),
         entered('business_years_at_current_location', 'Years at this location', 'number', subject='business'),
         entered('business_has_branches', 'Other business branches', 'boolean', subject='business'),
         entered('business_managed_full_time', 'Managed full time', 'boolean', subject='business'),
         entered('business_employee_count', 'Employees', 'number', subject='business'),
         entered('business_good_day_sales', 'Good-day sales', 'money', subject='business'),
         entered('business_low_day_sales', 'Low-day sales', 'money', subject='business'),
         entered('business_seasonal', 'Seasonal business', 'boolean', subject='business'),
         entered('business_peak_periods', 'Busy periods', subject='business'),
         entered('business_low_periods', 'Low periods', subject='business'),
         entered('business_customer_stock_estimate', 'Applicant stock estimate', 'money', subject='business'),
         entered('business_officer_stock_estimate', 'Officer stock estimate', 'money', subject='business', local=True),
         entered('business_stock_financing_history', 'How stock was financed', 'textarea', subject='business'),
         entered('business_challenges', 'Business challenges', 'textarea', subject='business'),
         entered('business_monthly_rent', 'Business rent', 'money', subject='business'),
         entered('preappraisal_assessment_notes', 'Officer assessment', 'textarea', local=True),
         entered('preappraisal_second_visit_recommended', 'Second visit recommended', 'boolean', local=True),
         entered('preappraisal_recommended_amount', 'Officer recommended amount', 'money', subject='loan', local=True),
         entered('preappraisal_affordable_payment', 'Affordable payment', 'money', subject='loan'),
         entered('preappraisal_affordable_frequency', 'Affordability frequency', subject='loan'),
         reuse('external_loans')),
        (_signer('borrower', 'Applicant', identity_fields={'name':'borrower_full_name','phone':'applicant_phone','national_id':'applicant_id_number'}),
         _signer('officer', 'Officer')),
        review_notes=('Printed Type and Box require owner clarification before placement.',
                      'Supervisor/committee decisions are not officer-entered approval values.',
                      'Photos, ID copies, statement and map pin remain evidence, not scalar text.'),
        document_role='supporting', required_signer_roles=('borrower','officer')),
    MainLafDefinition('logbook_offer', 'SUPPORT LAF- Logbook Offer Letter .pdf',
        'a95635785bfd8b253c6b4196c399626d1dff82a20c0b6bba48d46bd72b8a82bf', 622272, 4,
        'jawabu_logbook_offer', 'Logbook offer', None, SECTIONS,
        (*IDENTITY, generated('reference_number', 'Offer reference'), generated('application_date', 'Application date', pages=(2,)),
         generated('financed_principal_amount', 'Contract principal', pages=(2,2,2)),
         generated('installment_amount', 'Installment amount', pages=(2,)),
         generated('installment_count', 'Installment count', pages=(2,)),
         generated('contract_interest_rate_percent', 'Contract interest rate', pages=(2,)),
         entered('vehicle_registration_number', 'Vehicle registration', subject='vehicle', page=2),
         entered('offer_penalty_rate_percent', 'Offer penalty rate', 'number', subject='loan', local=True, page=2),
         entered('offer_processing_fee_rate_percent', 'Offer processing fee rate', 'number', subject='loan', local=True, page=2),
         entered('offer_risk_fund_rate_percent', 'Offer risk fund rate', 'number', subject='loan', local=True, page=2)),
        (), review_notes=('Printed working-capital purpose and fixed penalty clause require compliance review.',
                          'Fee/penalty blanks are not inferred from total fees or interest.',
                          'Approval sequence and authorized-signatory authority must be explicitly confirmed.'),
        document_role='supporting', required_signer_roles=('borrower','witness','branch_manager','management_approver')),
    MainLafDefinition('chattel_security', 'SUPPORT LAF- Logbook CHATTEL MORTGAGE.pdf',
        'f72923199e9ce5060c8872ab82955cafcd4410eec22beba8192e8bdc12109d95', 707552, 5,
        'jawabu_chattel_security', 'Vehicle security agreement', None, SECTIONS,
        (entered('grantor_name', 'Grantor name', subject='grantor'),
         entered('grantor_national_id', 'Grantor ID', 'national_id', subject='grantor'),
         entered('grantor_postal_address', 'Grantor postal address', subject='grantor'),
         generated('borrower_full_name', 'Borrower name'), reuse('applicant_postal_address'),
         entered('security_secured_principal', 'Secured principal', 'money', subject='loan', local=True),
         *VEHICLE, reuse('pledged_assets', page=4),
         entered('grantor_spouse_name', 'Grantor spouse', subject='grantor_spouse', page=4),
         entered('security_identified_by', 'Identified by', subject='document', local=True, page=4),
         entered('advocate_name', 'Advocate name', subject='document', local=True, page=5),
         entered('advocate_postal_address', 'Advocate postal address', subject='document', local=True, page=5),
         entered('affidavit_sworn_at', 'Sworn at', subject='document', local=True, page=5),
         entered('grantor_residence_address', 'Beneficial owner residence', subject='grantor', page=5),
         entered('grantor_nationality', 'Beneficial owner nationality', subject='grantor', page=5)),
        (), review_notes=('Grantor, spouse and advocate are distinct parties, not aliases for applicant or witness.',
                          'Execution, certification and affidavit dates belong to their exact signing/attestation events.'),
        document_role='supporting', required_signer_roles=('grantor','grantor_spouse','advocate','commissioner_for_oaths')),
    MainLafDefinition('vehicle_transfer', 'SUPPORT LAF- Logbook TRANSFER FORM.pdf',
        '6ac34912b4220bbc17f134509af90dbff6cd1bdeaac0220356001295328779cd', 110836, 2,
        'jawabu_vehicle_transfer', 'Vehicle transfer', None, SECTIONS,
        tuple(entered('vehicle_' + key, label, subject='vehicle') for key,label in [
            ('registration_number','Vehicle registration'), ('make','Vehicle make'), ('body_type','Vehicle body type'),
            ('chassis_number','Chassis number'), ('engine_number','Engine number'), ('insurance_provider','Third-party insurer')]) +
        tuple(entered(role + '_' + key, role.replace('_',' ').title() + ' ' + label, type, subject=role)
              for role in ['seller','proposed_owner'] for key,label,type in [
                  ('name','name','text'), ('national_id','ID','national_id'), ('postal_address','postal address','text'),
                  ('kra_pin','KRA PIN','text')]) +
        (entered('proposed_owner_phone','New owner phone','phone',subject='proposed_owner'),
         entered('proposed_owner_occupation','New owner occupation',subject='proposed_owner'),
         entered('proposed_owner_employer','New owner employer',subject='proposed_owner'),
         entered('vehicle_transfer_fee','Transfer fee','money',subject='document',local=True)),
        (), review_notes=('Company/institution applicants are outside this rollout.',
                          'Printed official-use boxes and the malformed location label remain unmapped.',
                          'Proposed owner is not the registered owner until authoritative transfer evidence exists.'),
        document_role='supporting', required_signer_roles=('seller','proposed_owner')),
)
DEFINITIONS_BY_KEY = {definition.key: definition for definition in DEFINITIONS}
