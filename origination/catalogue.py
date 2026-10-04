"""Explicit governance for adopted records; physical legacy tables are preserved."""
MODEL_METADATA = {'origination.LoanOriginationApplication': {'domain': 'origination',
                                            'purpose': 'Canonical, revision-controlled application captured by a field officer.',
                                            'classification': 'authoritative_record',
                                            'source_of_truth': True,
                                            'lifecycle': 'active',
                                            'retention': 'Retained with the owning business record according to its workflow policy.',
                                            'legacy_db_table': 'core_loanoriginationapplication',
                                            'index_justifications': {'core_loanor_officer_3c905e_idx': 'Preserved existing '
                                                                                                       'LoanOriginationApplication index for scoped '
                                                                                                       'operational lookup by officer, status, '
                                                                                                       'updated_at; avoids changing live query '
                                                                                                       'performance during ownership transfer.',
                                                                     'core_loanor_branch_8c321c_idx': 'Preserved existing LoanOriginationApplication '
                                                                                                      'index for scoped operational lookup by '
                                                                                                      'branch, status, updated_at; avoids changing '
                                                                                                      'live query performance during ownership '
                                                                                                      'transfer.'}},
 'origination.OriginationApplicationDocument': {'domain': 'origination',
                                                'purpose': 'Application-scoped snapshot and progress for one generated packet document.',
                                                'classification': 'authoritative_record',
                                                'source_of_truth': True,
                                                'lifecycle': 'active',
                                                'retention': 'Retained with the owning business record according to its workflow policy.',
                                                'legacy_db_table': 'core_originationapplicationdocument',
                                                'index_justifications': {}},
 'origination.OriginationApplicationEvent': {'domain': 'origination',
                                             'purpose': 'Append-only operational history for an origination application.',
                                             'classification': 'immutable_event',
                                             'source_of_truth': True,
                                             'lifecycle': 'active',
                                             'retention': 'Retained with the permanent workflow or compliance audit record.',
                                             'legacy_db_table': 'core_originationapplicationevent',
                                             'index_justifications': {'core_origin_applica_ea7e72_idx': 'Preserved existing '
                                                                                                        'OriginationApplicationEvent index for '
                                                                                                        'scoped operational lookup by application, '
                                                                                                        'occurred_at; avoids changing live query '
                                                                                                        'performance during ownership transfer.'}},
 'origination.OriginationCommercialException': {'domain': 'origination',
                                                'purpose': 'Immutable Superuser approval for exact policy mismatches on one revision.',
                                                'classification': 'authoritative_record',
                                                'source_of_truth': True,
                                                'lifecycle': 'active',
                                                'retention': 'Retained with the owning business record according to its workflow policy.',
                                                'legacy_db_table': 'core_originationcommercialexception',
                                                'index_justifications': {'orig_comm_exception_rev_idx': 'Preserved existing '
                                                                                                        'OriginationCommercialException index for '
                                                                                                        'scoped operational lookup by application, '
                                                                                                        'application_revision; avoids changing live '
                                                                                                        'query performance during ownership '
                                                                                                        'transfer.'}},
 'origination.OriginationConsentPolicyVersion': {'domain': 'origination',
                                                 'purpose': 'Immutable approved wording bound to a conditional signing packet.',
                                                 'classification': 'authoritative_record',
                                                 'source_of_truth': True,
                                                 'lifecycle': 'active',
                                                 'retention': 'Retained with the owning business record according to its workflow policy.',
                                                 'legacy_db_table': 'core_originationconsentpolicyversion',
                                                 'index_justifications': {}},
 'origination.OriginationCorrectionItem': {'domain': 'origination',
                                           'purpose': 'Immutable field or requirement target within a correction request.',
                                           'classification': 'processing_record',
                                           'source_of_truth': True,
                                           'lifecycle': 'active',
                                           'retention': 'Retained with the owning business record according to its workflow policy.',
                                           'legacy_db_table': 'core_originationcorrectionitem',
                                           'index_justifications': {}},
 'origination.OriginationCorrectionRequest': {'domain': 'origination',
                                              'purpose': 'Append-preserving reviewer instructions for one submitted revision.',
                                              'classification': 'authoritative_record',
                                              'source_of_truth': True,
                                              'lifecycle': 'active',
                                              'retention': 'Retained with the owning business record according to its workflow policy.',
                                              'legacy_db_table': 'core_originationcorrectionrequest',
                                              'index_justifications': {'orig_corr_app_status_idx': 'Preserved existing OriginationCorrectionRequest '
                                                                                                   'index for scoped operational lookup by '
                                                                                                   'application, status, created_at; avoids changing '
                                                                                                   'live query performance during ownership '
                                                                                                   'transfer.'}},
 'origination.OriginationDataField': {'domain': 'origination',
                                      'purpose': 'Global semantic field used by product forms and legal PDF mappings.',
                                      'classification': 'authoritative_record',
                                      'source_of_truth': True,
                                      'lifecycle': 'active',
                                      'retention': 'Retained with the owning business record according to its workflow policy.',
                                      'legacy_db_table': 'core_originationdatafield',
                                      'index_justifications': {'core_origin_active_c188a9_idx': 'Preserved existing OriginationDataField index for '
                                                                                                'scoped operational lookup by active, category, '
                                                                                                'label; avoids changing live query performance '
                                                                                                'during ownership transfer.'}},
 'origination.OriginationDataFieldEvent': {'domain': 'origination',
                                           'purpose': 'Append-only, value-free audit trail for catalogue governance.',
                                           'classification': 'immutable_event',
                                           'source_of_truth': True,
                                           'lifecycle': 'active',
                                           'retention': 'Retained with the permanent workflow or compliance audit record.',
                                           'legacy_db_table': 'core_originationdatafieldevent',
                                           'index_justifications': {}},
 'origination.OriginationDocumentProductEligibility': {'domain': 'origination',
                                                       'purpose': 'Current product allowlist for one immutable Origination catalogue document '
                                                                  'version.',
                                                       'classification': 'business_link',
                                                       'source_of_truth': True,
                                                       'lifecycle': 'active',
                                                       'retention': 'Retained while the catalogue document or product history requires it.',
                                                       'legacy_db_table': 'core_originationdocumentproducteligibility',
                                                       'index_justifications': {}},
 'origination.OriginationDocumentTemplate': {'domain': 'origination',
                                             'purpose': 'Immutable Drive-backed PDF/config pair approved for origination rendering.',
                                             'classification': 'configuration',
                                             'source_of_truth': True,
                                             'lifecycle': 'active',
                                             'retention': 'Retain while referenced; retire or deactivate instead of deleting governed history.',
                                             'legacy_db_table': 'core_originationdocumenttemplate',
                                             'index_justifications': {}},
 'origination.OriginationDocumentTemplateEvent': {'domain': 'origination',
                                                  'purpose': 'Append-only audit trail for legal template lifecycle changes.',
                                                  'classification': 'immutable_event',
                                                  'source_of_truth': True,
                                                  'lifecycle': 'active',
                                                  'retention': 'Retained with the permanent workflow or compliance audit record.',
                                                  'legacy_db_table': 'core_originationdocumenttemplateevent',
                                                  'index_justifications': {}},
 'origination.OriginationFieldReviewIssue': {'domain': 'origination',
                                             'purpose': 'Tracked exit path for a legacy schema field without a safe catalogue binding.',
                                             'classification': 'authoritative_record',
                                             'source_of_truth': True,
                                             'lifecycle': 'active',
                                             'retention': 'Retained with the owning business record according to its workflow policy.',
                                             'legacy_db_table': 'core_originationfieldreviewissue',
                                             'index_justifications': {'core_origin_status_85057f_idx': 'Preserved existing '
                                                                                                       'OriginationFieldReviewIssue index for scoped '
                                                                                                       'operational lookup by status, updated_at; '
                                                                                                       'avoids changing live query performance '
                                                                                                       'during ownership transfer.'}},
 'origination.OriginationOtpChallenge': {'domain': 'origination',
                                         'purpose': 'Hashed, bounded OTP challenge; provider delivery never proves signing.',
                                         'classification': 'processing_record',
                                         'source_of_truth': True,
                                         'lifecycle': 'temporary',
                                         'retention': 'Service-managed bounded retention; see the owning service and deployment settings.',
                                         'legacy_db_table': 'core_originationotpchallenge',
                                         'index_justifications': {}},
 'origination.OriginationProductDefinition': {'domain': 'origination',
                                              'purpose': 'Versioned, inactive-by-default contract for one loan-origination form.',
                                              'classification': 'configuration',
                                              'source_of_truth': True,
                                              'lifecycle': 'active',
                                              'retention': 'Retain while referenced; retire or deactivate instead of deleting governed history.',
                                              'legacy_db_table': 'core_originationproductdefinition',
                                              'index_justifications': {'core_origin_product_67c040_idx': 'Preserved existing '
                                                                                                         'OriginationProductDefinition index for '
                                                                                                         'scoped operational lookup by product_key, '
                                                                                                         'is_active; avoids changing live query '
                                                                                                         'performance during ownership transfer.'}},
 'origination.OriginationProductDefinitionEvent': {'domain': 'origination',
                                                   'purpose': 'Append-only lifecycle history for a versioned origination product.',
                                                   'classification': 'immutable_event',
                                                   'source_of_truth': True,
                                                   'lifecycle': 'active',
                                                   'retention': 'Retained with the permanent workflow or compliance audit record.',
                                                   'legacy_db_table': 'core_originationproductdefinitionevent',
                                                   'index_justifications': {}},
 'origination.OriginationProductDocumentAssignment': {'domain': 'origination',
                                                      'purpose': 'Version-policy assignment between a legacy product definition and document family.',
                                                      'classification': 'business_assignment',
                                                      'source_of_truth': True,
                                                      'lifecycle': 'compatibility',
                                                      'retention': 'Retained for historical product-definition and application compatibility.',
                                                      'legacy_db_table': 'core_originationproductdocumentassignment',
                                                      'index_justifications': {}},
 'origination.OriginationReportingValue': {'domain': 'origination',
                                           'purpose': 'Rebuildable typed projection of explicitly reportable application values.',
                                           'classification': 'authoritative_record',
                                           'source_of_truth': True,
                                           'lifecycle': 'active',
                                           'retention': 'Retained with the owning business record according to its workflow policy.',
                                           'legacy_db_table': 'core_originationreportingvalue',
                                           'index_justifications': {'orig_report_field_text_idx': 'Preserved existing OriginationReportingValue '
                                                                                                  'index for scoped operational lookup by '
                                                                                                  'data_field, text_value; avoids changing live '
                                                                                                  'query performance during ownership transfer.',
                                                                    'orig_report_field_num_idx': 'Preserved existing OriginationReportingValue index '
                                                                                                 'for scoped operational lookup by data_field, '
                                                                                                 'decimal_value; avoids changing live query '
                                                                                                 'performance during ownership transfer.',
                                                                    'orig_report_field_date_idx': 'Preserved existing OriginationReportingValue '
                                                                                                  'index for scoped operational lookup by '
                                                                                                  'data_field, date_value; avoids changing live '
                                                                                                  'query performance during ownership transfer.',
                                                                    'orig_report_field_bool_idx': 'Preserved existing OriginationReportingValue '
                                                                                                  'index for scoped operational lookup by '
                                                                                                  'data_field, boolean_value; avoids changing live '
                                                                                                  'query performance during ownership transfer.',
                                                                    'orig_report_field_choice_idx': 'Preserved existing OriginationReportingValue '
                                                                                                    'index for scoped operational lookup by '
                                                                                                    'data_field, choice_code; avoids changing live '
                                                                                                    'query performance during ownership transfer.'}},
 'origination.OriginationRequirementEvidence': {'domain': 'origination',
                                                'purpose': 'Audited Drive-backed evidence for one snapshotted product requirement.',
                                                'classification': 'authoritative_record',
                                                'source_of_truth': True,
                                                'lifecycle': 'active',
                                                'retention': 'Retained with the owning business record according to its workflow policy.',
                                                'legacy_db_table': 'core_originationrequirementevidence',
                                                'index_justifications': {'orig_evid_app_req_status_idx': 'Preserved existing '
                                                                                                         'OriginationRequirementEvidence index for '
                                                                                                         'scoped operational lookup by application, '
                                                                                                         'requirement_key, status; avoids changing '
                                                                                                         'live query performance during ownership '
                                                                                                         'transfer.'}},
 'origination.OriginationReviewerNotice': {'domain': 'origination',
                                           'purpose': 'Persistent in-app attention item for an Origination checker.',
                                           'classification': 'authoritative_record',
                                           'source_of_truth': True,
                                           'lifecycle': 'active',
                                           'retention': 'Retained with the owning business record according to its workflow policy.',
                                           'legacy_db_table': 'core_originationreviewernotice',
                                           'index_justifications': {}},
 'origination.OriginationSignerSession': {'domain': 'origination',
                                          'purpose': 'Revocable bearer session for one signer of one immutable packet.',
                                          'classification': 'authoritative_record',
                                          'source_of_truth': True,
                                          'lifecycle': 'temporary',
                                          'retention': 'Service-managed bounded retention; see the owning service and deployment settings.',
                                          'legacy_db_table': 'core_originationsignersession',
                                          'index_justifications': {}},
 'origination.OriginationSigningAction': {'domain': 'origination',
                                          'purpose': 'Append-only evidence for one simulated or provider-verified slot action.',
                                          'classification': 'authoritative_record',
                                          'source_of_truth': True,
                                          'lifecycle': 'active',
                                          'retention': 'Retained with the owning business record according to its workflow policy.',
                                          'legacy_db_table': 'core_originationsigningaction',
                                          'index_justifications': {}},
 'origination.OriginationSigningActionInvalidation': {'domain': 'origination',
                                                      'purpose': 'Append-only checker evidence invalidating one otherwise immutable action.',
                                                      'classification': 'authoritative_record',
                                                      'source_of_truth': True,
                                                      'lifecycle': 'active',
                                                      'retention': 'Retained with the owning business record according to its workflow policy.',
                                                      'legacy_db_table': 'core_originationsigningactioninvalidation',
                                                      'index_justifications': {}},
 'origination.OriginationSigningPackage': {'domain': 'origination',
                                           'purpose': 'Stable cross-system link from one frozen revision to e-signatures.',
                                           'classification': 'authoritative_record',
                                           'source_of_truth': True,
                                           'lifecycle': 'active',
                                           'retention': 'Retained with the owning business record according to its workflow policy.',
                                           'legacy_db_table': 'core_originationsigningpackage',
                                           'index_justifications': {'core_origin_applica_3a6bd3_idx': 'Preserved existing OriginationSigningPackage '
                                                                                                      'index for scoped operational lookup by '
                                                                                                      'application, status, updated_at; avoids '
                                                                                                      'changing live query performance during '
                                                                                                      'ownership transfer.'}},
 'origination.OriginationSigningRequestEvent': {'domain': 'origination',
                                                'purpose': 'Minimal append-only database throttle evidence for public signing writes.',
                                                'classification': 'immutable_event',
                                                'source_of_truth': True,
                                                'lifecycle': 'active',
                                                'retention': 'Retained with the permanent workflow or compliance audit record.',
                                                'legacy_db_table': 'core_originationsigningrequestevent',
                                                'index_justifications': {'core_osre_token_created_idx': 'Preserved existing '
                                                                                                        'OriginationSigningRequestEvent index for '
                                                                                                        'scoped operational lookup by action, '
                                                                                                        'token_hash, created_at; avoids changing '
                                                                                                        'live query performance during ownership '
                                                                                                        'transfer.',
                                                                         'core_osre_ip_created_idx': 'Preserved existing '
                                                                                                     'OriginationSigningRequestEvent index for '
                                                                                                     'scoped operational lookup by action, '
                                                                                                     'source_ip_hash, created_at; avoids changing '
                                                                                                     'live query performance during ownership '
                                                                                                     'transfer.'}},
 'origination.OriginationStampAsset': {'domain': 'origination',
                                       'purpose': 'Versioned, controlled PNG used only in calibrated stamp slots.',
                                       'classification': 'authoritative_record',
                                       'source_of_truth': True,
                                       'lifecycle': 'active',
                                       'retention': 'Retained with the owning business record according to its workflow policy.',
                                       'legacy_db_table': 'core_originationstampasset',
                                       'index_justifications': {}},
 'origination.OriginationTemplateConfigurationRevision': {'domain': 'origination',
                                                          'purpose': 'Append-only saved calibration revision for one immutable source PDF.',
                                                          'classification': 'authoritative_record',
                                                          'source_of_truth': True,
                                                          'lifecycle': 'active',
                                                          'retention': 'Retained with the owning business record according to its workflow policy.',
                                                          'legacy_db_table': 'core_originationtemplateconfigurationrevision',
                                                          'index_justifications': {}}}
