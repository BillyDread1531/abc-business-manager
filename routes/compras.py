
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion


compras_bp = Blueprint(
    "compras",
    __name__,
    url_prefix="/compras"
)


# ============================================================
# CREAR PROVEEDOR
# ============================================================

@compras_bp.route("/proveedor/nuevo", methods=["GET", "POST"])
def nuevo_proveedor():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        nombre = request.form.get(
            "nombre",
            ""
        ).strip()


        if nombre:

            nombre = " ".join(
                palabra[:1].upper()
                + palabra[1:].lower()

                for palabra in nombre.split()
            )
        telefono = request.form.get("telefono", "").strip() or None
        email = request.form.get("email", "").strip() or None
        direccion = request.form.get("direccion", "").strip() or None
        notas = request.form.get("notas", "").strip() or None

        try:

            if not nombre:
                raise ValueError(
                    "El nombre del proveedor es obligatorio."
                )

            cursor.execute("""
                INSERT INTO proveedores (
                    nombre,
                    telefono,
                    email,
                    direccion,
                    notas,
                    activo
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    1
                )
            """, (
                nombre,
                telefono,
                email,
                direccion,
                notas
            ))

            conn.commit()

            flash(
                f"Proveedor '{nombre}' creado correctamente.",
                "success"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for("compras.nueva")
            )

        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo crear el proveedor: {e}",
                "danger"
            )

    cursor.close()
    conn.close()

    return render_template(
        "compras/nuevo_proveedor.html"
    )

# ============================================================
# LISTA DE COMPRAS
# ============================================================

@compras_bp.route("/")
def lista():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    filtro = request.args.get(
        "filtro",
        "todos"
    ).strip().lower()


    filtros_validos = {
        "todos",
        "pendiente",
        "recibida",
        "cancelada",
        "pago_pendiente"
    }


    if filtro not in filtros_validos:
        filtro = "todos"


    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)


    condiciones = []
    parametros = []


    # ========================================================
    # BUSCADOR
    # ========================================================

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                c.numero LIKE %s
                OR p.nombre LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino
        ])


    # ========================================================
    # FILTROS DE ESTADO
    # ========================================================

    if filtro == "pendiente":

        condiciones.append(
            "c.estado = 'PENDIENTE'"
        )


    elif filtro == "recibida":

        condiciones.append(
            "c.estado = 'RECIBIDA'"
        )


    elif filtro == "cancelada":

        condiciones.append(
            "c.estado = 'CANCELADA'"
        )


    where_sql = ""

    if condiciones:

        where_sql = (
            "WHERE "
            + " AND ".join(condiciones)
        )


    # ========================================================
    # COMPRAS
    # ========================================================

    cursor.execute(
        f"""
        SELECT
            c.id,
            c.numero,
            c.fecha,
            c.subtotal,
            c.descuento,
            c.total,
            c.estado,
            c.notas,

            p.nombre AS proveedor,

            u.nombre AS usuario,

            COALESCE(
                pagos.total_pagado,
                0
            ) AS total_pagado

        FROM compras c

        LEFT JOIN proveedores p
            ON c.proveedor_id = p.id

        INNER JOIN usuarios u
            ON c.usuario_id = u.id

        LEFT JOIN (
            SELECT
                compra_id,
                SUM(monto) AS total_pagado

            FROM pagos_compras

            GROUP BY compra_id
        ) pagos
            ON pagos.compra_id = c.id

        {where_sql}

        ORDER BY
            c.fecha DESC,
            c.id DESC
        """,
        tuple(parametros)
    )


    compras = cursor.fetchall()


    # ========================================================
    # FILTRO PENDIENTE DE PAGO
    # ========================================================

    if filtro == "pago_pendiente":

        compras = [
            compra
            for compra in compras
            if (
                compra["estado"] != "CANCELADA"
                and
                compra["total_pagado"]
                < compra["total"]
            )
        ]


    # ========================================================
    # CONTADORES
    # ========================================================

    cursor.execute("""
        SELECT

            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN estado = 'PENDIENTE'
                    THEN 1
                    ELSE 0
                END
            ) AS pendientes,

            SUM(
                CASE
                    WHEN estado = 'RECIBIDA'
                    THEN 1
                    ELSE 0
                END
            ) AS recibidas,

            SUM(
                CASE
                    WHEN estado = 'CANCELADA'
                    THEN 1
                    ELSE 0
                END
            ) AS canceladas

        FROM compras
    """)

    contadores = cursor.fetchone()


    cursor.execute("""
        SELECT
            COUNT(*) AS pendientes_pago

        FROM compras c

        LEFT JOIN (
            SELECT
                compra_id,
                SUM(monto) AS total_pagado

            FROM pagos_compras

            GROUP BY compra_id
        ) pagos
            ON pagos.compra_id = c.id

        WHERE c.estado != 'CANCELADA'
          AND COALESCE(
                pagos.total_pagado,
                0
              ) < c.total
    """)

    resultado_pago = cursor.fetchone()


    contadores["pendientes_pago"] = (
        resultado_pago["pendientes_pago"]
        if resultado_pago
        else 0
    )


    cursor.close()
    conn.close()


    return render_template(
        "compras/lista.html",

        compras=compras,

        busqueda=busqueda,
        filtro=filtro,

        contadores=contadores
    )
# ============================================================
# NUEVA COMPRA
# ============================================================

@compras_bp.route("/nueva", methods=["GET", "POST"])
def nueva():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        proveedor_id = request.form.get("proveedor_id") or None
        fecha = request.form.get("fecha")
        descuento = request.form.get("descuento", "0")
        notas = request.form.get("notas", "").strip() or None

        material_ids = request.form.getlist("material_id[]")
        cantidades = request.form.getlist("cantidad[]")
        precios = request.form.getlist("precio_unitario[]")
        subtotales_linea = request.form.getlist("subtotal_linea[]")
        anchos_reales = request.form.getlist("ancho_real_cm[]")

        try:

            if not material_ids:
                raise ValueError(
                    "Debes agregar al menos un material a la compra."
                )

            if not (
                len(material_ids)
                == len(cantidades)
                == len(precios)
                == len(subtotales_linea)
                == len(anchos_reales)
            ):
                raise ValueError(
                    "Los datos de los materiales están incompletos."
                )

            detalles_compra = []
            subtotal = 0.0

            for i in range(len(material_ids)):

                material_id = material_ids[i]

                if not material_id:
                    raise ValueError(
                        "Debes seleccionar un material en todas las filas."
                    )

                try:
                    cantidad = float(cantidades[i] or 0)
                except (TypeError, ValueError):
                    cantidad = 0

                if cantidad <= 0:
                    raise ValueError(
                        "La cantidad debe ser mayor que cero."
                    )

                # Se permite trabajar de dos formas:
                # 1. Precio unitario -> calcula subtotal.
                # 2. Total de la línea -> calcula precio unitario.
                try:
                    precio_unitario = float(precios[i] or 0)
                except (TypeError, ValueError):
                    precio_unitario = 0

                try:
                    subtotal_ingresado = float(
                        subtotales_linea[i] or 0
                    )
                except (TypeError, ValueError):
                    subtotal_ingresado = 0

                if precio_unitario < 0 or subtotal_ingresado < 0:
                    raise ValueError(
                        "Los precios no pueden ser negativos."
                    )

                if precio_unitario <= 0 and subtotal_ingresado <= 0:
                    raise ValueError(
                        "Debes indicar el precio unitario o el total "
                        "del material."
                    )

                # El subtotal escrito manualmente tiene prioridad.
                if subtotal_ingresado > 0:
                    subtotal_detalle = round(
                        subtotal_ingresado,
                        2
                    )
                    precio_unitario = (
                        subtotal_detalle / cantidad
                    )
                else:
                    subtotal_detalle = round(
                        cantidad * precio_unitario,
                        2
                    )

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.modo_control,
                        m.ancho_referencia_cm,
                        m.unidad_compra_id,
                        m.unidad_consumo_id,

                        uc.nombre AS unidad,
                        uc.abreviatura,
                        uc.tipo AS tipo_compra,
                        uc.factor_conversion AS factor_compra,

                        ucons.tipo AS tipo_consumo,
                        ucons.factor_conversion AS factor_consumo

                    FROM materiales m

                    INNER JOIN unidades_medida uc
                        ON m.unidad_compra_id = uc.id

                    INNER JOIN unidades_medida ucons
                        ON m.unidad_consumo_id = ucons.id

                    WHERE m.id = %s
                      AND m.activo = 1
                """, (material_id,))

                material = cursor.fetchone()

                if not material:
                    raise ValueError(
                        "Uno de los materiales seleccionados no existe."
                    )

                ancho_real_cm = None

                if material["modo_control"] == "ROLLO_AREA":

                    try:
                        ancho_real_cm = float(
                            anchos_reales[i]
                            or material["ancho_referencia_cm"]
                            or 0
                        )
                    except (TypeError, ValueError):
                        ancho_real_cm = 0

                    if ancho_real_cm <= 0:
                        raise ValueError(
                            f"Debes indicar el ancho real del rollo "
                            f"para '{material['nombre']}'."
                        )

                    if material["tipo_compra"] != "LONGITUD":
                        raise ValueError(
                            f"'{material['nombre']}' está configurado como "
                            "rollo, pero su unidad de compra no es de longitud."
                        )

                    if material["tipo_consumo"] != "AREA":
                        raise ValueError(
                            f"'{material['nombre']}' está configurado como "
                            "rollo, pero su unidad de consumo no es de área."
                        )

                subtotal += subtotal_detalle

                detalles_compra.append({
                    "material_id": material_id,
                    "cantidad": cantidad,
                    "unidad_id": material["unidad_compra_id"],
                    "precio_unitario": precio_unitario,
                    "subtotal": subtotal_detalle,
                    "ancho_real_cm": ancho_real_cm
                })

            # ------------------------------------------------
            # Generar número de compra
            # ------------------------------------------------

            cursor.execute("""
                SELECT numero
                FROM compras
                ORDER BY id DESC
                LIMIT 1
            """)

            ultima = cursor.fetchone()

            if ultima:
                try:
                    ultimo_numero = int(
                        ultima["numero"].split("-")[-1]
                    )
                except (ValueError, AttributeError):
                    ultimo_numero = 0
            else:
                ultimo_numero = 0

            siguiente_numero = ultimo_numero + 1
            numero = f"COMP-{siguiente_numero:04d}"

            # ------------------------------------------------
            # Crear compra
            # ------------------------------------------------

            try:
                descuento_valor = float(descuento or 0)
            except (TypeError, ValueError):
                descuento_valor = 0

            if descuento_valor < 0:
                raise ValueError(
                    "El descuento no puede ser negativo."
                )

            subtotal = round(subtotal, 2)
            total = round(
                subtotal - descuento_valor,
                2
            )

            if total < 0:
                raise ValueError(
                    "El descuento no puede ser mayor que el subtotal."
                )

            cursor.execute("""
                INSERT INTO compras (
                    numero,
                    proveedor_id,
                    usuario_id,
                    fecha,
                    subtotal,
                    descuento,
                    total,
                    estado,
                    notas
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'PENDIENTE',
                    %s
                )
            """, (
                numero,
                proveedor_id,
                8,
                fecha if fecha else None,
                subtotal,
                descuento_valor,
                total,
                notas
            ))

            compra_id = cursor.lastrowid

            for detalle in detalles_compra:

                cursor.execute("""
                    INSERT INTO detalle_compra (
                        compra_id,
                        material_id,
                        variante_id,
                        cantidad,
                        unidad_id,
                        precio_unitario,
                        subtotal,
                        ancho,
                        largo
                    )
                    VALUES (
                        %s,
                        %s,
                        NULL,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NULL
                    )
                """, (
                    compra_id,
                    detalle["material_id"],
                    detalle["cantidad"],
                    detalle["unidad_id"],
                    detalle["precio_unitario"],
                    detalle["subtotal"],
                    detalle["ancho_real_cm"]
                ))

            # Un solo commit al final para guardar la compra completa.
            conn.commit()

            flash(
                f"Compra {numero} creada correctamente.",
                "success"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for(
                    "compras.detalle",
                    compra_id=compra_id
                )
            )

        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo crear la compra: {e}",
                "danger"
            )

    # --------------------------------------------------------
    # Proveedores
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM proveedores
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    proveedores = cursor.fetchall()

    # --------------------------------------------------------
    # Materiales disponibles
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.modo_control,
            m.ancho_referencia_cm,
            m.unidad_compra_id,
            m.unidad_consumo_id,
            m.cantidad_por_compra,
            m.costo_compra_referencia,

            uc.nombre AS unidad_compra,
            uc.abreviatura AS abreviatura_compra,
            uc.tipo AS tipo_compra,
            uc.factor_conversion AS factor_compra,

            ucons.nombre AS unidad_consumo,
            ucons.abreviatura AS abreviatura_consumo,
            ucons.tipo AS tipo_consumo,
            ucons.factor_conversion AS factor_consumo

        FROM materiales m

        INNER JOIN unidades_medida uc
            ON m.unidad_compra_id = uc.id

        INNER JOIN unidades_medida ucons
            ON m.unidad_consumo_id = ucons.id

        WHERE m.activo = 1
        ORDER BY m.nombre ASC
    """)

    materiales = cursor.fetchall()

    # --------------------------------------------------------
    # Fecha actual
    # --------------------------------------------------------

    from datetime import date
    fecha_actual = date.today().isoformat()

    cursor.close()
    conn.close()

    return render_template(
        "compras/nueva.html",
        proveedores=proveedores,
        materiales=materiales,
        fecha_actual=fecha_actual
    )


# ============================================================
# DETALLE DE COMPRA
# ============================================================

@compras_bp.route("/<int:compra_id>")
def detalle(compra_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    # --------------------------------------------------------
    # Compra
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            c.*,
            p.nombre AS proveedor,
            u.nombre AS usuario

        FROM compras c

        LEFT JOIN proveedores p
            ON c.proveedor_id = p.id

        INNER JOIN usuarios u
            ON c.usuario_id = u.id

        WHERE c.id = %s
    """, (compra_id,))

    compra = cursor.fetchone()

    if not compra:

        cursor.close()
        conn.close()

        flash(
            "La compra no existe.",
            "danger"
        )

        return redirect(
            url_for("compras.lista")
        )


    # --------------------------------------------------------
    # Detalles
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            dc.id,
            dc.cantidad,
            dc.unidad_id,
            dc.precio_unitario,
            dc.subtotal,
            dc.ancho,
            dc.largo,

            m.nombre AS material,
            m.color,

            u.nombre AS unidad,
            u.abreviatura

        FROM detalle_compra dc

        LEFT JOIN materiales m
            ON dc.material_id = m.id

        INNER JOIN unidades_medida u
            ON dc.unidad_id = u.id

        WHERE dc.compra_id = %s

        ORDER BY dc.id ASC
    """, (compra_id,))

    detalles = cursor.fetchall()


    # --------------------------------------------------------
    # Materiales disponibles
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.unidad_compra_id,

            u.nombre AS unidad,
            u.abreviatura

        FROM materiales m

        INNER JOIN unidades_medida u
            ON m.unidad_compra_id = u.id

        WHERE m.activo = 1

        ORDER BY m.nombre ASC
    """)

    materiales = cursor.fetchall()


    # --------------------------------------------------------
    # PAGOS DE LA COMPRA
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            fecha,
            monto,
            metodo_pago,
            referencia,
            notas
        FROM pagos_compras
        WHERE compra_id = %s
        ORDER BY fecha DESC, id DESC
    """, (compra_id,))

    pagos = cursor.fetchall()


    # --------------------------------------------------------
    # TOTAL PAGADO Y SALDO PENDIENTE
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS total_pagado
        FROM pagos_compras
        WHERE compra_id = %s
    """, (compra_id,))

    resultado_pago = cursor.fetchone()

    total_pagado = float(
        resultado_pago["total_pagado"] or 0
    )

    saldo_pendiente = (
        float(compra["total"] or 0)
        - total_pagado
    )

    if saldo_pendiente < 0:
        saldo_pendiente = 0


    # --------------------------------------------------------
    # CERRAR CONEXIÓN
    # --------------------------------------------------------

    cursor.close()
    conn.close()


    return render_template(
        "compras/detalle.html",
        compra=compra,
        detalles=detalles,
        materiales=materiales,
        pagos=pagos,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente
    )

# ============================================================
# REGISTRAR PAGO DE COMPRA
# ============================================================

@compras_bp.route(
    "/<int:compra_id>/pago/nuevo",
    methods=["GET", "POST"]
)
def registrar_pago(compra_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # Obtener compra
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                c.id,
                c.numero,
                c.total,
                c.estado,
                c.proveedor_id,
                p.nombre AS proveedor

            FROM compras c

            LEFT JOIN proveedores p
                ON c.proveedor_id = p.id

            WHERE c.id = %s
        """, (compra_id,))

        compra = cursor.fetchone()

        if not compra:
            raise ValueError(
                "La compra no existe."
            )

        if compra["estado"] == "CANCELADA":
            raise ValueError(
                "No puedes registrar pagos en una compra cancelada."
            )

        # ----------------------------------------------------
        # Calcular lo pagado
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                COALESCE(SUM(monto), 0) AS total_pagado
            FROM pagos_compras
            WHERE compra_id = %s
        """, (compra_id,))

        resultado = cursor.fetchone()

        total_pagado = float(
            resultado["total_pagado"] or 0
        )

        saldo_pendiente = (
            float(compra["total"] or 0)
            - total_pagado
        )

        if saldo_pendiente <= 0:
            raise ValueError(
                "Esta compra ya está pagada completamente."
            )

        # ----------------------------------------------------
        # Guardar pago
        # ----------------------------------------------------

        if request.method == "POST":

            monto = float(
                request.form.get("monto") or 0
            )

            metodo_pago = request.form.get(
                "metodo_pago"
            )

            referencia = request.form.get(
                "referencia",
                ""
            ).strip() or None

            notas = request.form.get(
                "notas",
                ""
            ).strip() or None

            if monto <= 0:
                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if monto > saldo_pendiente:
                raise ValueError(
                    f"El pago supera el saldo pendiente "
                    f"de Q{saldo_pendiente:.2f}."
                )

            if metodo_pago not in (
                "EFECTIVO",
                "TRANSFERENCIA",
                "TARJETA",
                "OTRO"
            ):
                raise ValueError(
                    "El método de pago no es válido."
                )

            # ------------------------------------------------
            # Registrar pago de compra
            # ------------------------------------------------

            cursor.execute("""
                INSERT INTO pagos_compras (
                    compra_id,
                    proveedor_id,
                    usuario_id,
                    monto,
                    metodo_pago,
                    referencia,
                    notas
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                compra_id,
                compra["proveedor_id"],
                8,
                monto,
                metodo_pago,
                referencia,
                notas
            ))

            # ------------------------------------------------
            # Registrar egreso financiero
            # ------------------------------------------------

            cursor.execute("""
                INSERT INTO egresos (
                    pedido_id,
                    proveedor_id,
                    compra_id,
                    usuario_id,
                    categoria,
                    monto,
                    descripcion
                )
                VALUES (
                    NULL,
                    %s,
                    %s,
                    %s,
                    'COMPRA',
                    %s,
                    %s
                )
            """, (
                compra["proveedor_id"],
                compra_id,
                8,
                monto,
                f"Pago de compra {compra['numero']}"
            ))

            conn.commit()

            flash(
                f"Pago de Q{monto:.2f} registrado correctamente.",
                "success"
            )

            return redirect(
                url_for(
                    "compras.detalle",
                    compra_id=compra_id
                )
            )

        # ----------------------------------------------------
        # Mostrar formulario
        # ----------------------------------------------------

        return render_template(
            "compras/registrar_pago.html",
            compra=compra,
            total_pagado=total_pagado,
            saldo_pendiente=saldo_pendiente
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo registrar el pago: {e}",
            "danger"
        )

        return redirect(
            url_for(
                "compras.detalle",
                compra_id=compra_id
            )
        )

    finally:

        cursor.close()
        conn.close()

# ============================================================
# RECIBIR COMPRA
# ============================================================
@compras_bp.route("/<int:compra_id>/recibir", methods=["POST"])
def recibir(compra_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # Obtener la compra
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                numero,
                estado
            FROM compras
            WHERE id = %s
            FOR UPDATE
        """, (compra_id,))

        compra = cursor.fetchone()

        if not compra:
            raise ValueError(
                "La compra no existe."
            )

        # ----------------------------------------------------
        # Verificar estado
        # ----------------------------------------------------

        if compra["estado"] == "RECIBIDA":

            raise ValueError(
                "Esta compra ya fue recibida."
            )

        if compra["estado"] == "CANCELADA":

            raise ValueError(
                "No se puede recibir una compra cancelada."
            )

        # ----------------------------------------------------
        # Obtener detalles de la compra
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                dc.id,
                dc.material_id,
                dc.cantidad,
                dc.unidad_id,
                dc.precio_unitario,
                dc.subtotal,
                dc.ancho,

                m.nombre,
                m.modo_control,
                m.ancho_referencia_cm,
                m.unidad_compra_id,
                m.unidad_consumo_id,
                m.cantidad_por_compra,

                uc.nombre AS unidad_compra,
                uc.abreviatura AS abreviatura_compra,
                uc.tipo AS tipo_compra,
                uc.factor_conversion AS factor_compra,

                ucons.nombre AS unidad_consumo,
                ucons.abreviatura AS abreviatura_consumo,
                ucons.tipo AS tipo_consumo,
                ucons.factor_conversion AS factor_consumo

            FROM detalle_compra dc

            INNER JOIN materiales m
                ON dc.material_id = m.id

            INNER JOIN unidades_medida uc
                ON m.unidad_compra_id = uc.id

            INNER JOIN unidades_medida ucons
                ON m.unidad_consumo_id = ucons.id

            WHERE dc.compra_id = %s

            ORDER BY dc.id ASC
        """, (compra_id,))

        detalles = cursor.fetchall()

        if not detalles:

            raise ValueError(
                "La compra no tiene materiales."
            )

        # ----------------------------------------------------
        # Procesar cada material
        # ----------------------------------------------------

        for detalle in detalles:

            material_id = detalle["material_id"]

            cantidad_compra = float(
                detalle["cantidad"]
            )

            precio_unitario = float(
                detalle["precio_unitario"]
            )

            unidad_compra = detalle["unidad_compra_id"]
            unidad_consumo = detalle["unidad_consumo_id"]

            tipo_compra = detalle["tipo_compra"]
            tipo_consumo = detalle["tipo_consumo"]

            factor_compra = float(
                detalle["factor_compra"] or 1
            )

            factor_consumo = float(
                detalle["factor_consumo"] or 1
            )

            cantidad_por_compra = float(
                detalle["cantidad_por_compra"] or 1
            )

            # ------------------------------------------------
            # Convertir a unidad de consumo
            # ------------------------------------------------

            if detalle["modo_control"] == "ROLLO_AREA":

                if tipo_compra != "LONGITUD":
                    raise ValueError(
                        f"'{detalle['nombre']}' está configurado "
                        "como rollo, pero la unidad de compra "
                        "no es de longitud."
                    )

                if tipo_consumo != "AREA":
                    raise ValueError(
                        f"'{detalle['nombre']}' está configurado "
                        "como rollo, pero la unidad de consumo "
                        "no es de área."
                    )

                ancho_real_cm = float(
                    detalle["ancho"]
                    or detalle["ancho_referencia_cm"]
                    or 0
                )

                if ancho_real_cm <= 0:
                    raise ValueError(
                        f"No hay un ancho válido para "
                        f"'{detalle['nombre']}'."
                    )

                # factor_compra expresa la unidad de compra
                # en centímetros.
                largo_total_cm = (
                    cantidad_compra
                    * factor_compra
                )

                area_total_cm2 = (
                    largo_total_cm
                    * ancho_real_cm
                )

                # factor_consumo expresa la unidad de consumo
                # en cm².
                cantidad_consumo = (
                    area_total_cm2
                    / factor_consumo
                )

            elif unidad_compra == unidad_consumo:

                cantidad_consumo = cantidad_compra

            elif tipo_compra == tipo_consumo:

                cantidad_consumo = (
                    cantidad_compra
                    * factor_compra
                    / factor_consumo
                )

            else:

                cantidad_consumo = (
                    cantidad_compra
                    * cantidad_por_compra
                )

            if cantidad_consumo <= 0:

                raise ValueError(
                    f"La cantidad convertida de "
                    f"'{detalle['nombre']}' no es válida."
                )

            # ------------------------------------------------
            # Calcular costo por unidad de consumo
            # ------------------------------------------------

            costo_total = (
                cantidad_compra
                * precio_unitario
            )

            costo_unitario_consumo = (
                costo_total
                / cantidad_consumo
            )

            # ------------------------------------------------
            # Actualizar stock
            # ------------------------------------------------

            cursor.execute("""
                UPDATE materiales
                SET
                    stock_actual = stock_actual + %s,
                    costo_compra_referencia = %s
                WHERE id = %s
            """, (
                cantidad_consumo,
                precio_unitario,
                material_id
            ))

            # ------------------------------------------------
            # Crear lote de inventario
            # ------------------------------------------------

            cursor.execute("""
                INSERT INTO lotes_inventario (
                    material_id,
                    variante_id,
                    compra_id,
                    detalle_compra_id,
                    cantidad_original,
                    cantidad_actual,
                    unidad_id,
                    ancho,
                    largo,
                    area_total,
                    area_disponible,
                    costo_total,
                    costo_unitario,
                    activo
                )
                VALUES (
                    %s,
                    NULL,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NULL,
                    NULL,
                    %s,
                    %s,
                    1
                )
            """, (
                material_id,
                compra_id,
                detalle["id"],
                cantidad_consumo,
                cantidad_consumo,
                unidad_consumo,
                (
                    float(detalle["ancho"])
                    if detalle["modo_control"] == "ROLLO_AREA"
                    and detalle["ancho"] is not None
                    else None
                ),
                (
                    cantidad_compra * factor_compra
                    if detalle["modo_control"] == "ROLLO_AREA"
                    else None
                ),
                costo_total,
                costo_unitario_consumo
            ))

            lote_id = cursor.lastrowid

            # ------------------------------------------------
            # Registrar movimiento de inventario
            # ------------------------------------------------

            cursor.execute("""
                INSERT INTO movimientos_inventario (
                    material_id,
                    variante_id,
                    tipo,
                    cantidad,
                    unidad_id,
                    costo_unitario,
                    referencia_tipo,
                    referencia_id,
                    usuario_id,
                    notas
                )
                VALUES (
                    %s,
                    NULL,
                    'COMPRA',
                    %s,
                    %s,
                    %s,
                    'COMPRA',
                    %s,
                    %s,
                    %s
                )
            """, (
                material_id,
                cantidad_consumo,
                unidad_consumo,
                costo_unitario_consumo,
                compra_id,
                8,
                f"Recepción de compra {compra['numero']}"
            ))

        # ----------------------------------------------------
        # Marcar compra como recibida
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE compras
            SET estado = 'RECIBIDA'
            WHERE id = %s
        """, (compra_id,))

        # ----------------------------------------------------
        # Confirmar toda la operación
        # ----------------------------------------------------

        conn.commit()

        flash(
            f"Compra {compra['numero']} recibida correctamente. "
            "El inventario fue actualizado.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo recibir la compra: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "compras.detalle",
            compra_id=compra_id
        )
    )

@compras_bp.route("/<int:compra_id>/cancelar", methods=["POST"])
def cancelar(compra_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                numero,
                estado
            FROM compras
            WHERE id = %s
            FOR UPDATE
        """, (compra_id,))

        compra = cursor.fetchone()

        if not compra:
            raise ValueError(
                "La compra no existe."
            )

        if compra["estado"] == "RECIBIDA":
            raise ValueError(
                "No se puede cancelar una compra que ya fue recibida."
            )

        if compra["estado"] == "CANCELADA":
            raise ValueError(
                "Esta compra ya está cancelada."
            )

        cursor.execute("""
            UPDATE compras
            SET estado = 'CANCELADA'
            WHERE id = %s
        """, (compra_id,))

        conn.commit()

        flash(
            f"Compra {compra['numero']} cancelada correctamente.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo cancelar la compra: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "compras.detalle",
            compra_id=compra_id
        )
    )


# ============================================================
# LISTA DE PROVEEDORES
# ============================================================

@compras_bp.route("/proveedores")
def proveedores():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    filtro = request.args.get(
        "filtro",
        "todos"
    ).strip().lower()

    filtros_validos = {
        "todos",
        "activos",
        "inactivos",
        "saldo"
    }

    if filtro not in filtros_validos:
        filtro = "todos"

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    condiciones = []
    parametros = []

    # --------------------------------------------------------
    # BUSCADOR
    # --------------------------------------------------------

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                p.nombre LIKE %s
                OR p.telefono LIKE %s
                OR p.email LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino,
            termino
        ])

    # --------------------------------------------------------
    # FILTROS
    # --------------------------------------------------------

    if filtro == "activos":

        condiciones.append(
            "p.activo = 1"
        )

    elif filtro == "inactivos":

        condiciones.append(
            "p.activo = 0"
        )

    elif filtro == "saldo":

        condiciones.append("""
            COALESCE(
                resumen.saldo_pendiente,
                0
            ) > 0
        """)

    where_sql = ""

    if condiciones:

        where_sql = (
            "WHERE "
            + " AND ".join(condiciones)
        )

    # --------------------------------------------------------
    # PROVEEDORES + ESTADO DE CUENTA
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            p.id,
            p.nombre,
            p.telefono,
            p.email,
            p.direccion,
            p.notas,
            p.activo,
            p.creado_en,
            p.actualizado_en,

            COALESCE(
                resumen.total_compras,
                0
            ) AS total_compras,

            COALESCE(
                resumen.total_comprado,
                0
            ) AS total_comprado,

            COALESCE(
                resumen.total_pagado,
                0
            ) AS total_pagado,

            COALESCE(
                resumen.saldo_pendiente,
                0
            ) AS saldo_pendiente

        FROM proveedores p

        LEFT JOIN (

            SELECT
                c.proveedor_id,

                COUNT(*) AS total_compras,

                SUM(
                    CASE
                        WHEN c.estado != 'CANCELADA'
                        THEN c.total
                        ELSE 0
                    END
                ) AS total_comprado,

                SUM(
                    CASE
                        WHEN c.estado != 'CANCELADA'
                        THEN COALESCE(
                            pagos.total_pagado,
                            0
                        )
                        ELSE 0
                    END
                ) AS total_pagado,

                SUM(
                    CASE
                        WHEN c.estado != 'CANCELADA'
                        THEN GREATEST(
                            c.total
                            -
                            COALESCE(
                                pagos.total_pagado,
                                0
                            ),
                            0
                        )
                        ELSE 0
                    END
                ) AS saldo_pendiente

            FROM compras c

            LEFT JOIN (
                SELECT
                    compra_id,
                    SUM(monto) AS total_pagado
                FROM pagos_compras
                GROUP BY compra_id
            ) pagos
                ON pagos.compra_id = c.id

            WHERE c.proveedor_id IS NOT NULL

            GROUP BY c.proveedor_id

        ) resumen
            ON resumen.proveedor_id = p.id

        {where_sql}

        ORDER BY
            p.activo DESC,
            p.nombre ASC
        """,
        tuple(parametros)
    )

    proveedores = cursor.fetchall()

    # --------------------------------------------------------
    # CONTADORES
    # --------------------------------------------------------

    cursor.execute("""
        SELECT

            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN activo = 1
                    THEN 1
                    ELSE 0
                END
            ) AS activos,

            SUM(
                CASE
                    WHEN activo = 0
                    THEN 1
                    ELSE 0
                END
            ) AS inactivos

        FROM proveedores
    """)

    contadores = cursor.fetchone()

    cursor.execute("""
        SELECT
            COUNT(*) AS con_saldo

        FROM (

            SELECT
                c.proveedor_id

            FROM compras c

            LEFT JOIN (
                SELECT
                    compra_id,
                    SUM(monto) AS total_pagado
                FROM pagos_compras
                GROUP BY compra_id
            ) pagos
                ON pagos.compra_id = c.id

            WHERE c.proveedor_id IS NOT NULL
            AND c.estado != 'CANCELADA'

            GROUP BY c.proveedor_id

            HAVING SUM(
                GREATEST(
                    c.total
                    -
                    COALESCE(
                        pagos.total_pagado,
                        0
                    ),
                    0
                )
            ) > 0

        ) pendientes
    """)

    resultado_saldo = cursor.fetchone()

    contadores["con_saldo"] = (
        resultado_saldo["con_saldo"]
        if resultado_saldo
        else 0
    )

    cursor.close()
    conn.close()

    return render_template(
        "compras/proveedores.html",
        proveedores=proveedores,
        busqueda=busqueda,
        filtro=filtro,
        contadores=contadores
    )


# ============================================================
# DETALLE / ESTADO DE CUENTA DEL PROVEEDOR
# ============================================================

@compras_bp.route("/proveedor/<int:proveedor_id>")
def proveedor_detalle(proveedor_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    # --------------------------------------------------------
    # PROVEEDOR
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            nombre,
            telefono,
            email,
            direccion,
            notas,
            activo,
            creado_en,
            actualizado_en
        FROM proveedores
        WHERE id = %s
    """, (proveedor_id,))

    proveedor = cursor.fetchone()

    if not proveedor:

        cursor.close()
        conn.close()

        flash(
            "El proveedor no existe.",
            "danger"
        )

        return redirect(
            url_for("compras.proveedores")
        )

    # --------------------------------------------------------
    # COMPRAS DEL PROVEEDOR
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            c.id,
            c.numero,
            c.fecha,
            c.subtotal,
            c.descuento,
            c.total,
            c.estado,
            c.notas,

            COALESCE(
                pagos.total_pagado,
                0
            ) AS total_pagado,

            CASE
                WHEN c.estado = 'CANCELADA'
                THEN 0
                ELSE GREATEST(
                    c.total
                    -
                    COALESCE(
                        pagos.total_pagado,
                        0
                    ),
                    0
                )
            END AS saldo_pendiente

        FROM compras c

        LEFT JOIN (
            SELECT
                compra_id,
                SUM(monto) AS total_pagado
            FROM pagos_compras
            GROUP BY compra_id
        ) pagos
            ON pagos.compra_id = c.id

        WHERE c.proveedor_id = %s

        ORDER BY
            c.fecha DESC,
            c.id DESC
    """, (proveedor_id,))

    compras_proveedor = cursor.fetchall()

    # --------------------------------------------------------
    # TOTALES
    # --------------------------------------------------------

    total_comprado = 0.0
    total_pagado = 0.0
    saldo_pendiente = 0.0
    compras_activas = 0

    for compra in compras_proveedor:

        if compra["estado"] == "CANCELADA":
            continue

        total_comprado += float(
            compra["total"] or 0
        )

        total_pagado += float(
            compra["total_pagado"] or 0
        )

        saldo_pendiente += float(
            compra["saldo_pendiente"] or 0
        )

        compras_activas += 1

    # --------------------------------------------------------
    # PAGOS RECIENTES
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            pc.id,
            pc.fecha,
            pc.monto,
            pc.metodo_pago,
            pc.referencia,
            pc.notas,

            c.id AS compra_id,
            c.numero AS compra_numero

        FROM pagos_compras pc

        INNER JOIN compras c
            ON pc.compra_id = c.id

        WHERE pc.proveedor_id = %s

        ORDER BY
            pc.fecha DESC,
            pc.id DESC

        LIMIT 10
    """, (proveedor_id,))

    pagos_recientes = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "compras/proveedor_detalle.html",

        proveedor=proveedor,
        compras=compras_proveedor,
        pagos_recientes=pagos_recientes,

        total_comprado=total_comprado,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente,
        total_compras=compras_activas
    )