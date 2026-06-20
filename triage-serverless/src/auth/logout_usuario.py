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

        # 1. Intentar obtener el token desde invocación directa
        if 'token' in event:
            token = event['token']

        # 2. Intentar obtener el token desde el Body
        if not token:
            body = event.get('body', {})
            if isinstance(body, str):
                body = json.loads(body)
            if isinstance(body, dict):
                token = body.get('token')

        # 3. Intentar obtener el token desde la cabecera Authorization
        if not token:
            token = event.get('headers', {}).get('Authorization', '')

        # Si no se proporcionó ningún token, no podemos cerrar nada
        if not token:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Token no proporcionado para el cierre de sesión'
                })
            }

        # Conectar a la tabla de sesiones
        tabla_tokens = dynamodb.Table(TABLE_TOKENS)

        # 🌟 EL TRUCO: Borramos el token de la base de datos de inmediato.
        # Nota: "delete_item" en DynamoDB es genial porque si el token ya no existía 
        # (o ya se había borrado por el TTL), no explota; simplemente responde con éxito.
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