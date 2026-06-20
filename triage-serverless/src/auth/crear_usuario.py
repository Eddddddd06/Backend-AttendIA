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
    Crea un usuario en t_usuarios.

    Roles soportados:
      - 'admin'    → Dueño de la PYME. Debe incluir nombre_empresa.
                     Su tenant_id es el ID único de su empresa.
                     Solo el admin puede crear empleados
      - 'empleado' → Especialista registrado por el admin.
                     Tiene un area asignada (ej: "Ventas").

    Body requerido:
        tenant_id     - ID de la empresa (lo elige el admin en su registro)
        correo        - Email del usuario (SK en DynamoDB)
        password      - Contraseña en texto plano (se guarda como hash SHA-256)
        rol           - "admin" | "empleado"
        area          - Área del empleado (requerido si rol == 'empleado')
        nombre_empresa- Nombre visible de la empresa (requerido si rol == 'admin')
    """
    try:
        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)
        if not isinstance(body, dict):
            body = {}

        # 1. Leer datos básicos del body
        correo = body.get('correo', '').strip()
        password = body.get('password', '')
        rol = body.get('rol', 'empleado').strip().lower()

        # ── CONTROL DE ACCESOS Y ROLES ──────────────────────────────────
        if rol == 'admin':
            # El registro de ADMIN sigue siendo público (creación de cuenta de empresa)
            tenant_id = body.get('tenant_id', '').strip()
            nombre_empresa = body.get('nombre_empresa', '').strip()
            areas = body.get('areas', [])
            area = None # Un admin no pertenece a un área individual
            
            # Validación obligatoria para el Admin
            if not all([tenant_id, correo, password, nombre_empresa]):
                return {
                    'statusCode': 400,
                    'body': json.dumps({'status': 'error', 'message': 'Campos requeridos para Admin: tenant_id, correo, password, nombre_empresa'})
                }

        elif rol == 'empleado':
            # 🌟 EL EMPLEADO ES PRIVADO: Requiere que el Admin esté logueado
            token = event.get('headers', {}).get('Authorization', '')
            if not token:
                return {
                    'statusCode': 401,
                    'body': json.dumps({'status': 'error', 'message': 'No autorizado. Se requiere token de administrador.'})
                }

            # Invocamos internamente al validador de tokens (Lambda-to-Lambda)
            lambda_client = boto3.client('lambda')
            payload_string = '{ "token": "' + token + '" }'
            invoke_response = lambda_client.invoke(
                FunctionName=f"{SERVICE_NAME}-{STAGE}-ValidarTokenAcceso",
                InvocationType='RequestResponse',
                Payload=payload_string
            )
            response_validador = json.loads(invoke_response['Payload'].read())
            
            if response_validador.get('statusCode') == 403:
                return {
                    'statusCode': 403,
                    'body': json.dumps({'status': 'error', 'message': 'Forbidden - Token de administrador inválido o expirado'})
                }

            # Extraemos los datos SEGUROS de la sesión del Administrador
            token_data = json.loads(response_validador.get('body', '{}')).get('data', {})
            
            # Doble check: Asegurarnos de que quien usa el token realmente sea un ADMIN
            if token_data.get('rol') != 'admin':
                return {
                    'statusCode': 403,
                    'body': json.dumps({'status': 'error', 'message': 'Forbidden - Solo los administradores pueden registrar empleados'})
                }

            # 🌟 MAGIA ULTRA-EFICIENTE: Heredamos los datos directamente del Admin logueado
            tenant_id = token_data.get('tenant_id')
            nombre_empresa = token_data.get('nombre_empresa')
            
            # Datos específicos del empleado que vienen en el body
            area = body.get('area', '').strip()
            areas = None # Un empleado no tiene un catálogo de áreas entero

            if not all([correo, password, area]):
                return {
                    'statusCode': 400,
                    'body': json.dumps({'status': 'error', 'message': 'Campos requeridos para Empleado: correo, password, area'})
                }
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'El rol debe ser "admin" o "empleado"'})
            }

        # 2. Seguridad: Criptografía (Hash de la contraseña)
        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

        # 3. Conexión a DynamoDB y validación de duplicados
        tabla = dynamodb.Table(TABLE_USUARIOS)
        existing = tabla.get_item(Key={'tenant_id': tenant_id, 'correo': correo})
        
        if 'Item' in existing:
            return {
                'statusCode': 409,
                'body': json.dumps({'status': 'error', 'message': 'Ya existe un usuario con ese correo en esta empresa'})
            }

        # 4. Construcción del objeto final limpio (Sin strings vacíos)
        item = {
            'tenant_id': tenant_id,
            'correo': correo,
            'password_hash': password_hash,
            'rol': rol,
            'nombre_empresa': nombre_empresa # Ambos lo tienen (¡Excelente para el frontend del empleado!)
        }

        if rol == 'admin':
            item['areas'] = areas
        else:
            item['area'] = area

        # 5. Guardar en la base de datos
        tabla.put_item(Item=item)

        return {
            'statusCode': 201,
            'body': json.dumps({
                'status': 'success',
                'message': f'Usuario con rol "{rol}" creado exitosamente por el administrador' if rol == 'empleado' else 'Empresa y Administrador registrados exitosamente',
                'data': {
                    'tenant_id': tenant_id,
                    'correo': correo,
                    'rol': rol
                }
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] crear_usuario: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }