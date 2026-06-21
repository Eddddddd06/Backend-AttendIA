import boto3
import json
import hashlib
import os

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido de Administrador.
    Permite al Admin modificar los datos de un empleado (Área y/o Contraseña).
    """
    try:
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

        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)

        token_data = json.loads(response.get('body', '{}')).get('data', {})
        tenant_id = token_data.get('tenant_id')
        rol_usuario = token_data.get('rol')
        correo_admin = token_data.get('correo')

        if rol_usuario != 'admin':
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Forbidden - Solo los administradores pueden modificar usuarios'
                })
            }

        correo_empleado = body.get('correo_empleado', '').strip()
        nueva_area = body.get('area')
        nueva_password = body.get('password')

        if not correo_empleado:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'Falta el campo requerido: correo_empleado'})
            }

        tabla = dynamodb.Table(TABLE_USUARIOS)

        res_empleado = tabla.get_item(Key={'tenant_id': tenant_id, 'correo': correo_empleado})
        if 'Item' not in res_empleado:
            return {
                'statusCode': 404,
                'body': json.dumps({'status': 'error', 'message': 'El empleado especificado no existe en tu empresa'})
            }
        
        if res_empleado['Item'].get('rol') != 'empleado':
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'No puedes modificar a otro administrador desde este módulo'})
            }

        update_expression = "SET"
        expression_attribute_values = {}
        fields_updated = []

        if nueva_area is not None:
            nueva_area = nueva_area.strip()
            
            res_admin = tabla.get_item(Key={'tenant_id': tenant_id, 'correo': correo_admin})
            catalogo_areas = res_admin.get('Item', {}).get('areas', [])

            if nueva_area not in catalogo_areas:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'status': 'error',
                        'message': f'El área "{nueva_area}" no existe en el catálogo de tu empresa. Áreas disponibles: {catalogo_areas}'
                    })
                }
            
            update_expression += " area = :area,"
            expression_attribute_values[":area"] = nueva_area
            fields_updated.append("area")

        if nueva_password:
            password_hash = hashlib.sha256(nueva_password.encode('utf-8')).hexdigest()
            update_expression += " password_hash = :password_hash,"
            expression_attribute_values[":password_hash"] = password_hash
            fields_updated.append("password")

        if not fields_updated:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'No se proporcionaron campos para actualizar (area o password)'})
            }

        update_expression = update_expression.rstrip(',')

        tabla.update_item(
            Key={'tenant_id': tenant_id, 'correo': correo_empleado},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': f'Empleado actualizado correctamente. Campos modificados: {", ".join(fields_updated)}'
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] actualizar_usuario: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
