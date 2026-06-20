import boto3
import json
import os

dynamodb = boto3.resource('dynamodb')
TABLE_TOKENS = os.environ.get('DYNAMODB_TOKENS_TABLE', 't_tokens_acceso')


def lambda_handler(event, context):
    """
    Valida si un token existe en t_tokens_acceso.
    Puede recibir el token desde:
      - event['token']  (invocación directa lambda-to-lambda)
      - event['body']['token'] (API Gateway)
      - event['headers']['Authorization'] (API Gateway con header)
    """
    try:
        token = None

        # 1. Intento directo (invocación lambda-to-lambda)
        if 'token' in event:
            token = event['token']

        # 2. Desde body
        if not token:
            body = event.get('body', {})
            if isinstance(body, str):
                body = json.loads(body)
            token = body.get('token')

        # 3. Desde header Authorization
        if not token:
            token = event.get('headers', {}).get('Authorization', '')

        if not token:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'Token no proporcionado'})
            }

        # Buscar token en DynamoDB
        tabla_tokens = dynamodb.Table(TABLE_TOKENS)
        result = tabla_tokens.get_item(
            Key={'token': token}
        )

        if 'Item' not in result:
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'Forbidden',
                    'message': 'Token inválido o expirado'
                })
            }

        item = result['Item']

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'valid',
                'message': 'Token válido',
                'data': {
                    'tenant_id': item.get('tenant_id'),
                    'correo': item.get('correo'),
                    'rol': item.get('rol'),
                    'area': item.get('area')
                }
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
