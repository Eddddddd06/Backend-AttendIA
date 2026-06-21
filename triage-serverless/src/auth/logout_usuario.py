import boto3
import json
import os

dynamodb = boto3.resource('dynamodb')
TABLE_TOKENS = os.environ.get('DYNAMODB_TOKENS_TABLE', 't_tokens_acceso')


def lambda_handler(event, context):
    """
    Cierra la sesión del usuario invalidando su token.
    Puede recibir el token desde:
      - event['token']                     (Invocación directa)
      - event['body']['token']             (API Gateway Body JSON)
      - event['headers']['Authorization']   (API Gateway Header)
    """
    try:
        token = None

        if 'token' in event:
            token = event['token']

        if not token:
            body = event.get('body', {})
            if isinstance(body, str):
                body = json.loads(body)
            if isinstance(body, dict):
                token = body.get('token')

        if not token:
            token = event.get('headers', {}).get('Authorization', '')

        if not token:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Token no proporcionado para el cierre de sesión'
                })
            }

        tabla_tokens = dynamodb.Table(TABLE_TOKENS)

        
        tabla_tokens.delete_item(
            Key={'token': token}
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': 'Sesión cerrada correctamente. El token ha sido invalidado.'
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] logout: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
