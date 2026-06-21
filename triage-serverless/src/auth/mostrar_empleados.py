import boto3
import json
import os
dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')
def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido de Administrador.
    Lista todos los empleados registrados en la empresa del admin.
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
                'body': json.dumps({'status': 'error', 'message': 'Forbidden - Acceso No Autorizado'})
            }
        token_data = json.loads(response.get('body', '{}')).get('data', {})
        tenant_id = token_data.get('tenant_id')
        rol_usuario = token_data.get('rol')
        if rol_usuario != 'admin':
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Forbidden - Solo los administradores pueden listar empleados'
                })
            }
        if not tenant_id:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'Token sin tenant_id válido'})
            }
        tabla = dynamodb.Table(TABLE_USUARIOS)
        resultado = tabla.query(
            IndexName='RolIndex',
            KeyConditionExpression='rol = :rol AND tenant_id = :tenant_id',
            ExpressionAttributeValues={
                ':rol': 'empleado',
                ':tenant_id': tenant_id
            }
        )
        empleados = []
        for item in resultado.get('Items', []):
            empleados.append({
                'correo': item.get('correo', ''),
                'area': item.get('area', ''),
                'rol': item.get('rol', 'empleado'),
                'nombre_empresa': item.get('nombre_empresa', '')
            })
        admin_item = tabla.get_item(
            Key={'tenant_id': tenant_id, 'correo': token_data.get('correo', '')}
        ).get('Item', {})
        areas = admin_item.get('areas', [])
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'total': len(empleados),
                'areas': areas,
                'data': empleados
            })
        }
    except Exception as e:
        print(f"[ERROR] obtener_empleados: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
