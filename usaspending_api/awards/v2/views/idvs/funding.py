from collections import OrderedDict
from copy import deepcopy

from psycopg2.sql import Identifier, Literal, SQL
from rest_framework.request import Request
from rest_framework.response import Response

from usaspending_api.common.cache_decorator import cache_response
from usaspending_api.common.helpers.generic_helper import get_simple_pagination_metadata
from usaspending_api.common.helpers.sql_helpers import build_composable_order_by, execute_sql_to_ordered_dictionary
from usaspending_api.common.views import APIDocumentationView
from usaspending_api.core.validator.award import get_internal_or_generated_award_id_model
from usaspending_api.core.validator.pagination import customize_pagination_with_sort_columns
from usaspending_api.core.validator.tinyshield import TinyShield


SORTABLE_COLUMNS = {
    'account_title': ['taa.account_title'],
    'object_class': ['oc.object_class_name', 'oc.object_class'],
    'piid': ['ca.piid'],
    'program_activity': ['rpa.program_activity_code', 'rpa.program_activity_name'],
    'reporting_agency_name': ['taa.reporting_agency_name'],
    'reporting_fiscal_date': ['sa.reporting_fiscal_year', 'sa.reporting_fiscal_quarter'],
    'transaction_obligated_amount': ['faba.transaction_obligated_amount']
}

# Add a unique id to every sort key so results are deterministic.
for k, v in SORTABLE_COLUMNS.items():
    v.append('faba.financial_accounts_by_awards_id')

DEFAULT_SORT_COLUMN = 'reporting_fiscal_date'

# Get funding information for child and grandchild contracts of an IDV but
# not the IDVs themselves.
GET_FUNDING_SQL = SQL("""
    with cte as (
        select    award_id
        from      parent_award
        where     {award_id_column} = {award_id}
        union all
        select    cpa.award_id
        from      parent_award ppa
                  inner join parent_award cpa on cpa.parent_award_id = ppa.award_id
        where     ppa.{award_id_column} = {award_id}
    )
    select
        ca.id award_id,
        ca.generated_unique_award_id,
        sa.reporting_fiscal_year,
        sa.reporting_fiscal_quarter,
        ca.piid,
        taa.reporting_agency_name,
        taa.account_title,
        rpa.program_activity_code,
        rpa.program_activity_name,
        oc.object_class,
        oc.object_class_name,
        faba.transaction_obligated_amount
    from
        cte
        inner join awards pa on
            pa.id = cte.award_id
        inner join awards ca on
            ca.parent_award_piid = pa.piid and
            ca.fpds_parent_agency_id = pa.fpds_agency_id and
            ca.type not like 'IDV\_%'
        inner join financial_accounts_by_awards faba on
            faba.award_id = ca.id
        left outer join submission_attributes sa on
            sa.submission_id = faba.submission_id
        left outer join treasury_appropriation_account taa on
            taa.treasury_account_identifier = faba.treasury_account_id
        left outer join ref_program_activity rpa on
            rpa.id = faba.program_activity_id
        left outer join object_class oc on
            oc.id = faba.object_class_id
    where
        (ca.piid = {piid} or {piid} is null)
    {order_by}
    limit {limit} offset {offset}
""")


def _prepare_tiny_shield_models():
    models = customize_pagination_with_sort_columns(list(SORTABLE_COLUMNS.keys()), DEFAULT_SORT_COLUMN)
    models.extend([
        get_internal_or_generated_award_id_model(),
        {'key': 'piid', 'name': 'piid', 'optional': True, 'type': 'text', 'text_type': 'search'}
    ])
    return models


TINY_SHIELD_MODELS = _prepare_tiny_shield_models()


class IDVFundingViewSet(APIDocumentationView):
    """Returns File C funding records associated with an IDV."""

    @staticmethod
    def _parse_and_validate_request(request: Request) -> dict:
        return TinyShield(deepcopy(TINY_SHIELD_MODELS)).block(request)

    @staticmethod
    def _business_logic(request_data: dict) -> list:
        # By this point, our award_id has been validated and cleaned up by
        # TinyShield.  We will either have an internal award id that is an
        # integer or a generated award id that is a string.
        award_id = request_data['award_id']
        award_id_column = 'award_id' if type(award_id) is int else 'generated_unique_award_id'

        sql = GET_FUNDING_SQL.format(
            award_id_column=Identifier(award_id_column),
            award_id=Literal(award_id),
            piid=Literal(request_data.get('piid')),
            order_by=build_composable_order_by(SORTABLE_COLUMNS[request_data['sort']], request_data['order']),
            limit=Literal(request_data['limit'] + 1),
            offset=Literal((request_data['page'] - 1) * request_data['limit']),
        )

        return execute_sql_to_ordered_dictionary(sql)

    @cache_response()
    def post(self, request: Request) -> Response:
        request_data = self._parse_and_validate_request(request.data)
        results = self._business_logic(request_data)
        page_metadata = get_simple_pagination_metadata(len(results), request_data['limit'], request_data['page'])

        response = OrderedDict((
            ('results', results[:request_data['limit']]),
            ('page_metadata', page_metadata)
        ))

        return Response(response)