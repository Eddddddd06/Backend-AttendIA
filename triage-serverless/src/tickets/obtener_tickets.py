import boto3
import json
import os
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')


class DecimalEncoder(json.JSONEncoder):
    """Convierte tipos Decimal de DynamoDB a float para JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido.
    El Empleado o Admin consulta los tickets de su área o de su empresa.

    Parámetros (query string o body):
        tenant_area  - (Prioritario) Ej: "empresa1#Ventas" → filtra por área
        tenant_id    - (Alternativo) Devuelve todos los tickets del tenant
    """
    try:
        # ── Inicio: Proteger el Lambda ──────────────────────────────────
        token = event.get('headers', {}).get('Authorization', '')
        lambda_client = boto3.client('lambda')
        payload_string = '{ "token": "' + token + '" }'
        invoke_response = lambda_client.invoke(
            FunctionName=f"{SERVICE_NAME}-{STAGE}-ValidarTokenAcceso",
            InvocationType='RequestResponse',
            Payload=payload_string
        )
        response = json.loads(invoke_response['Payload'].read())
        if response.get('statusCode') == 403:
            return {
                'statusCode': 403,
                'body': json.dumps({'status': 'Forbidden - Acceso No Autorizado'})
            }
        # ── Fin: Proteger el Lambda ─────────────────────────────────────

        # Leer query string params o body
        query_params = event.get('queryStringParameters') or {}
        body = event.get('body', {})
        if isinstance(body, str) and body:
            body = json.loads(body)
        elif not isinstance(body, dict):
            body = {}

        tenant_area = query_params.get('tenant_area') or body.get('tenant_area')
        tenant_id = query_params.get('tenant_id') or body.get('tenant_id')

        if not tenant_area and not tenant_id:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Se requiere "tenant_area" (ej: empresa1#Ventas) o "tenant_id"'
                })
            }

        tabla_tickets = dynamodb.Table(TABLE_TICKETS)

        if tenant_area:
            # Query por GSI AreaScoreIndex → ordenado por score desc
            result = tabla_tickets.query(
                IndexName='AreaScoreIndex',
                KeyConditionExpression='tenant_area = :ta',
                ExpressionAttributeValues={':ta': tenant_area},
                ScanIndexForward=False  # score descendente (más urgente primero)
            )
        else:
            # Query por PK principal → todos los tickets del tenant
            result = tabla_tickets.query(
                KeyConditionExpression='tenant_id = :tid',
                ExpressionAttributeValues={':tid': tenant_id}
            )

        tickets = result.get('Items', [])

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'total': len(tickets),
                'data': tickets
            }, cls=DecimalEncoder)
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] obtener_tickets - JSON inválido: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Parámetros inválidos'})
        }
    except Exception as e:
        print(f"[ERROR] obtener_tickets: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
