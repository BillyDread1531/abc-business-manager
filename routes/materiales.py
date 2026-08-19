from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal

materiales_bp = Blueprint(
    "materiales",
    __name__,
    url_prefix="/materiales"
)


# ============================================================
# UTILIDADES DE PRESENTACIÓN
# ============================================================

def normalizar_texto_material(texto):

    if not texto:
        return texto

    palabras = texto.strip().split()
    resultado = []

    for palabra in palabras:

        if palabra.isupper():
            resultado.append(palabra)
        else:
            resultado.append(
                palabra[:1].upper()
                + palabra[1:].lower()
            )

    return " ".join(resultado)


def normalizar_color_material(texto):

    if not texto:
        return None

    texto = texto.strip()

    if not texto:
        return None

    return normalizar_texto_material(texto)


@materiales_bp.app_template_filter("numero_inteligente")
def numero_inteligente(valor):

    if valor is None:
        return "0"

    try:
        numero = Decimal(str(valor))
    except Exception:
        return str(valor)

    texto = f"{numero:.4f}".rstrip("0").rstrip(".")

    return texto if texto else "0"





def calcular_conversion_material(
    cursor,
    unidad_compra_id,
    unidad_consumo_id,
    modo_control,
    cantidad_manual,
    ancho_referencia_cm
):
    """
    Devuelve cuántas unidades de consumo representa UNA unidad de compra.

    NORMAL:
        - Si las unidades son del mismo tipo, usa factor_conversion.
        - Si son de tipos distintos, conserva cantidad_manual.

    ROLLO_AREA:
        - La unidad de compra debe ser LONGITUD.
        - La unidad de consumo debe ser AREA.
        - Usa el ancho de referencia en cm.

    Ejemplo:
        1 ft x 35 cm
        = 30.48 cm x 35 cm
        = 1066.8 cm²
    """

    cursor.execute("""
        SELECT
            id,
            nombre,
            abreviatura,
            tipo,
            factor_conversion
        FROM unidades_medida
        WHERE id IN (%s, %s)
    """, (
        unidad_compra_id,
        unidad_consumo_id
    ))

    unidades = {
        str(fila["id"]): fila
        for fila in cursor.fetchall()
    }

    compra = unidades.get(
        str(unidad_compra_id)
    )

    consumo = unidades.get(
        str(unidad_consumo_id)
    )

    if not compra or not consumo:
        raise ValueError(
            "Las unidades seleccionadas no son válidas."
        )

    factor_compra = Decimal(
        str(compra["factor_conversion"] or 1)
    )

    factor_consumo = Decimal(
        str(consumo["factor_conversion"] or 1)
    )

    if modo_control == "ROLLO_AREA":

        if compra["tipo"] != "LONGITUD":
            raise ValueError(
                "Para un material en rollo, la unidad de compra "
                "debe ser una unidad de longitud: pie, metro, yarda, etc."
            )

        if consumo["tipo"] != "AREA":
            raise ValueError(
                "Para un material en rollo, la unidad de consumo "
                "debe ser una unidad de área: cm², m², etc."
            )

        ancho = Decimal(
            str(ancho_referencia_cm or 0)
        )

        if ancho <= 0:
            raise ValueError(
                "Debes indicar un ancho habitual mayor que 0 cm."
            )

        # factor_compra queda expresado en centímetros.
        # factor_consumo queda expresado en cm².
        cantidad_por_compra = (
            factor_compra
            * ancho
            / factor_consumo
        )

        return cantidad_por_compra

    # Modo normal:
    if compra["tipo"] == consumo["tipo"]:

        return (
            factor_compra
            / factor_consumo
        )

    cantidad = Decimal(
        str(cantidad_manual or 0)
    )

    if cantidad <= 0:
        raise ValueError(
            "La cantidad por compra debe ser mayor que 0."
        )

    return cantidad


@materiales_bp.route("/")
def lista():

    busqueda = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "todos").strip().lower()

    filtros_validos = {
        "todos",
        "bajo",
        "agotado",
        "inactivo"
    }

    if filtro not in filtros_validos:
        filtro = "todos"

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    condiciones = []
    parametros = []

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                m.nombre LIKE %s
                OR m.color LIKE %s
                OR c.nombre LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino,
            termino
        ])

    if filtro == "bajo":

        condiciones.append("""
            m.activo = 1
            AND m.stock_actual > 0
            AND m.stock_actual <= m.stock_minimo
        """)

    elif filtro == "agotado":

        condiciones.append("""
            m.activo = 1
            AND m.stock_actual <= 0
        """)

    elif filtro == "inactivo":

        condiciones.append("""
            m.activo = 0
        """)

    where_sql = ""

    if condiciones:
        where_sql = (
            "WHERE "
            + " AND ".join(condiciones)
        )

    cursor.execute(
        f"""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.modo_control,
            m.ancho_referencia_cm,
            m.cantidad_por_compra,
            m.costo_compra_referencia,
            m.stock_actual,
            m.stock_minimo,
            m.activo,

            c.nombre AS categoria,

            uc.nombre AS unidad_compra,
            uc.abreviatura AS abreviatura_compra,

            ucons.nombre AS unidad_consumo,
            ucons.abreviatura AS abreviatura_consumo

        FROM materiales m

        LEFT JOIN categorias c
            ON m.categoria_id = c.id

        INNER JOIN unidades_medida uc
            ON m.unidad_compra_id = uc.id

        INNER JOIN unidades_medida ucons
            ON m.unidad_consumo_id = ucons.id

        {where_sql}

        ORDER BY
            m.activo DESC,
            m.nombre ASC
        """,
        tuple(parametros)
    )

    materiales = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN activo = 1
                     AND stock_actual > 0
                     AND stock_actual <= stock_minimo
                    THEN 1
                    ELSE 0
                END
            ) AS bajos,

            SUM(
                CASE
                    WHEN activo = 1
                     AND stock_actual <= 0
                    THEN 1
                    ELSE 0
                END
            ) AS agotados,

            SUM(
                CASE
                    WHEN activo = 0
                    THEN 1
                    ELSE 0
                END
            ) AS inactivos

        FROM materiales
    """)

    contadores = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "materiales/lista.html",
        materiales=materiales,
        busqueda=busqueda,
        filtro=filtro,
        contadores=contadores
    )


@materiales_bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        nombre = normalizar_texto_material(
            request.form.get("nombre", "")
        )

        color = normalizar_color_material(
            request.form.get("color", "")
        )

        categoria_id = (
            request.form.get("categoria_id")
            or None
        )

        familia_id = (
            request.form.get("familia_id")
            or None
        )

        unidad_compra_id = request.form.get(
            "unidad_compra_id"
        )

        unidad_consumo_id = request.form.get(
            "unidad_consumo_id"
        )

        modo_control = request.form.get(
            "modo_control",
            "NORMAL"
        ).strip().upper()

        if modo_control not in {
            "NORMAL",
            "ROLLO_AREA"
        }:
            modo_control = "NORMAL"

        cantidad_manual = request.form.get(
            "cantidad_por_compra",
            "1"
        )

        ancho_referencia_cm = (
            request.form.get(
                "ancho_referencia_cm"
            )
            or None
        )

        costo_compra_referencia = (
            request.form.get(
                "costo_compra_referencia",
                "0"
            )
            or "0"
        )

        stock_minimo = (
            request.form.get(
                "stock_minimo",
                "0"
            )
            or "0"
        )

        if not nombre:

            flash(
                "El nombre del material es obligatorio.",
                "danger"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for("materiales.nuevo")
            )

        if (
            not unidad_compra_id
            or not unidad_consumo_id
        ):

            flash(
                "Debes seleccionar la unidad de compra "
                "y la unidad de consumo.",
                "danger"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for("materiales.nuevo")
            )

        try:

            cantidad_por_compra = (
                calcular_conversion_material(
                    cursor,
                    unidad_compra_id,
                    unidad_consumo_id,
                    modo_control,
                    cantidad_manual,
                    ancho_referencia_cm
                )
            )

            costo_referencia = Decimal(
                str(costo_compra_referencia)
            )

            stock_minimo_decimal = Decimal(
                str(stock_minimo)
            )

            if costo_referencia < 0:
                raise ValueError(
                    "El costo de compra no puede ser negativo."
                )

            if stock_minimo_decimal < 0:
                raise ValueError(
                    "El stock mínimo no puede ser negativo."
                )

            cursor.execute("""
                INSERT INTO materiales (
                    categoria_id,
                    familia_id,
                    nombre,
                    color,
                    modo_control,
                    unidad_compra_id,
                    unidad_consumo_id,
                    cantidad_por_compra,
                    ancho_referencia_cm,
                    costo_compra_referencia,
                    stock_actual,
                    stock_minimo
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, 0, %s
                )
            """, (
                categoria_id,
                familia_id,
                nombre,
                color,
                modo_control,
                unidad_compra_id,
                unidad_consumo_id,
                cantidad_por_compra,
                (
                    ancho_referencia_cm
                    if modo_control == "ROLLO_AREA"
                    else None
                ),
                costo_referencia,
                stock_minimo_decimal
            ))

            conn.commit()

            flash(
                "Material creado correctamente.",
                "success"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for("materiales.lista")
            )

        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo crear el material: {e}",
                "danger"
            )

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM categorias
        ORDER BY nombre ASC
    """)

    categorias = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            nombre,
            abreviatura,
            tipo,
            factor_conversion
        FROM unidades_medida
        ORDER BY nombre ASC
    """)

    unidades = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            codigo,
            nombre
        FROM familias_materiales
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    familias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "materiales/nuevo.html",
        categorias=categorias,
        unidades=unidades,
        familias=familias
    )


# ============================================================
# ACTIVAR / DESACTIVAR MATERIAL
# ============================================================

@materiales_bp.route(
    "/<int:material_id>/cambiar-estado",
    methods=["POST"]
)
def cambiar_estado(material_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                nombre,
                activo
            FROM materiales
            WHERE id = %s
        """, (material_id,))

        material = cursor.fetchone()

        if not material:

            raise ValueError(
                "El material no existe."
            )


        nuevo_estado = 0 if material["activo"] else 1


        cursor.execute("""
            UPDATE materiales
            SET activo = %s
            WHERE id = %s
        """, (
            nuevo_estado,
            material_id
        ))

        conn.commit()


        if nuevo_estado:

            flash(
                f"El material '{material['nombre']}' fue activado.",
                "success"
            )

        else:

            flash(
                f"El material '{material['nombre']}' fue desactivado.",
                "success"
            )


    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo cambiar el estado del material: {e}",
            "danger"
        )


    cursor.close()
    conn.close()


    return redirect(
        url_for("materiales.lista")
    )



# ============================================================
# EDITAR MATERIAL
# ============================================================

@materiales_bp.route(
    "/<int:material_id>/editar",
    methods=["GET", "POST"]
)
def editar(material_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            categoria_id,
            familia_id,
            nombre,
            color,
            modo_control,
            unidad_compra_id,
            unidad_consumo_id,
            cantidad_por_compra,
            ancho_referencia_cm,
            costo_compra_referencia,
            stock_minimo,
            activo
        FROM materiales
        WHERE id = %s
    """, (material_id,))

    material = cursor.fetchone()

    if not material:

        cursor.close()
        conn.close()

        flash(
            "El material no existe.",
            "danger"
        )

        return redirect(
            url_for("materiales.lista")
        )

    if request.method == "POST":

        nombre = normalizar_texto_material(
            request.form.get("nombre", "")
        )

        color = normalizar_color_material(
            request.form.get("color", "")
        )

        categoria_id = (
            request.form.get("categoria_id")
            or None
        )

        familia_id = (
            request.form.get("familia_id")
            or None
        )

        unidad_compra_id = request.form.get(
            "unidad_compra_id"
        )

        unidad_consumo_id = request.form.get(
            "unidad_consumo_id"
        )

        modo_control = request.form.get(
            "modo_control",
            "NORMAL"
        ).strip().upper()

        if modo_control not in {
            "NORMAL",
            "ROLLO_AREA"
        }:
            modo_control = "NORMAL"

        cantidad_manual = request.form.get(
            "cantidad_por_compra",
            "1"
        )

        ancho_referencia_cm = (
            request.form.get(
                "ancho_referencia_cm"
            )
            or None
        )

        costo_compra_referencia = (
            request.form.get(
                "costo_compra_referencia",
                "0"
            )
            or "0"
        )

        stock_minimo = (
            request.form.get(
                "stock_minimo",
                "0"
            )
            or "0"
        )

        activo = (
            1
            if request.form.get("activo")
            else 0
        )

        if not nombre:

            flash(
                "El nombre del material es obligatorio.",
                "danger"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for(
                    "materiales.editar",
                    material_id=material_id
                )
            )

        if (
            not unidad_compra_id
            or not unidad_consumo_id
        ):

            flash(
                "Debes seleccionar la unidad de compra "
                "y la unidad de consumo.",
                "danger"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for(
                    "materiales.editar",
                    material_id=material_id
                )
            )

        try:

            cantidad_por_compra = (
                calcular_conversion_material(
                    cursor,
                    unidad_compra_id,
                    unidad_consumo_id,
                    modo_control,
                    cantidad_manual,
                    ancho_referencia_cm
                )
            )

            costo_referencia = Decimal(
                str(costo_compra_referencia)
            )

            stock_minimo_decimal = Decimal(
                str(stock_minimo)
            )

            if costo_referencia < 0:
                raise ValueError(
                    "El costo de compra no puede ser negativo."
                )

            if stock_minimo_decimal < 0:
                raise ValueError(
                    "El stock mínimo no puede ser negativo."
                )

            cursor.execute("""
                UPDATE materiales
                SET
                    categoria_id = %s,
                    familia_id = %s,
                    nombre = %s,
                    color = %s,
                    modo_control = %s,
                    unidad_compra_id = %s,
                    unidad_consumo_id = %s,
                    cantidad_por_compra = %s,
                    ancho_referencia_cm = %s,
                    costo_compra_referencia = %s,
                    stock_minimo = %s,
                    activo = %s
                WHERE id = %s
            """, (
                categoria_id,
                familia_id,
                nombre,
                color,
                modo_control,
                unidad_compra_id,
                unidad_consumo_id,
                cantidad_por_compra,
                (
                    ancho_referencia_cm
                    if modo_control == "ROLLO_AREA"
                    else None
                ),
                costo_referencia,
                stock_minimo_decimal,
                activo,
                material_id
            ))

            conn.commit()

            flash(
                "Material actualizado correctamente.",
                "success"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for("materiales.lista")
            )

        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo actualizar el material: {e}",
                "danger"
            )

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM categorias
        ORDER BY nombre ASC
    """)

    categorias = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            nombre,
            abreviatura,
            tipo,
            factor_conversion
        FROM unidades_medida
        ORDER BY nombre ASC
    """)

    unidades = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            codigo,
            nombre
        FROM familias_materiales
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    familias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "materiales/editar.html",
        material=material,
        categorias=categorias,
        unidades=unidades,
        familias=familias
    )


# ============================================================
# RECETA / MATERIALES DE UN PRODUCTO
# ============================================================

@materiales_bp.route("/producto/<int:producto_id>")
def materiales_producto(producto_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            p.id,
            p.nombre,
            p.descripcion,
            CAST(p.precio_base AS DECIMAL(12,2)) AS precio_base
        FROM productos p
        WHERE p.id = %s
          AND p.activo = 1
    """, (producto_id,))

    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conn.close()
        return "Producto no encontrado", 404

    # --------------------------------------------------------
    # Receta: material exacto o familia
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            pm.id,
            pm.modo_seleccion,
            pm.material_id,
            pm.familia_material_id,
            pm.cantidad,
            pm.unidad_id,
            pm.es_estimado,
            pm.notas,

            m.nombre AS material,
            m.color,
            m.modo_control,
            m.cantidad_por_compra,
            m.costo_compra_referencia,

            um.nombre AS unidad,
            um.abreviatura,

            fm.nombre AS familia,
            fm.codigo AS familia_codigo

        FROM producto_materiales pm

        LEFT JOIN materiales m
            ON pm.material_id = m.id

        LEFT JOIN unidades_medida um
            ON COALESCE(pm.unidad_id, m.unidad_consumo_id) = um.id

        LEFT JOIN familias_materiales fm
            ON pm.familia_material_id = fm.id

        WHERE pm.producto_id = %s

        ORDER BY
            pm.id ASC
    """, (producto_id,))

    materiales = cursor.fetchall()

    costo_total = Decimal("0.00")

    for receta in materiales:

        receta["costo_unitario"] = None
        receta["costo_total"] = None

        if (
            receta["modo_seleccion"] == "EXACTO"
            and receta["material_id"]
        ):

            cantidad = Decimal(
                str(receta["cantidad"] or 0)
            )

            cantidad_por_compra = Decimal(
                str(receta["cantidad_por_compra"] or 0)
            )

            costo_compra = Decimal(
                str(receta["costo_compra_referencia"] or 0)
            )

            if cantidad_por_compra > 0:

                costo_unitario = (
                    costo_compra
                    / cantidad_por_compra
                )

                costo_material = (
                    cantidad
                    * costo_unitario
                )

                receta["costo_unitario"] = costo_unitario
                receta["costo_total"] = costo_material

                # En rollos por área el costo final depende de las
                # medidas reales de cada pedido, así que esta cifra
                # solo es referencia si hay cantidad fija.
                if receta["modo_control"] != "ROLLO_AREA":
                    costo_total += costo_material

    margen = (
        Decimal(str(producto["precio_base"] or 0))
        - costo_total
    )

    # --------------------------------------------------------
    # Materiales exactos disponibles
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.familia_id,
            m.modo_control,
            m.unidad_consumo_id,

            u.nombre AS unidad_consumo,
            u.abreviatura AS abreviatura_consumo,

            fm.nombre AS familia

        FROM materiales m

        INNER JOIN unidades_medida u
            ON m.unidad_consumo_id = u.id

        LEFT JOIN familias_materiales fm
            ON m.familia_id = fm.id

        WHERE m.activo = 1

        ORDER BY
            fm.nombre ASC,
            m.nombre ASC,
            m.color ASC
    """)

    materiales_disponibles = cursor.fetchall()

    # --------------------------------------------------------
    # Familias disponibles
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            fm.id,
            fm.codigo,
            fm.nombre,
            COUNT(m.id) AS materiales_activos
        FROM familias_materiales fm

        LEFT JOIN materiales m
            ON m.familia_id = fm.id
           AND m.activo = 1

        WHERE fm.activo = 1

        GROUP BY
            fm.id,
            fm.codigo,
            fm.nombre

        ORDER BY fm.nombre ASC
    """)

    familias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "materiales/producto.html",
        producto=producto,
        materiales=materiales,
        materiales_disponibles=materiales_disponibles,
        familias=familias,
        costo_total=costo_total,
        margen=margen
    )


# ============================================================
# AGREGAR MATERIAL / FAMILIA A LA RECETA
# ============================================================

@materiales_bp.route(
    "/producto/<int:producto_id>/agregar",
    methods=["POST"]
)
def agregar_material_producto(producto_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    modo_seleccion = request.form.get(
        "modo_seleccion",
        "EXACTO"
    ).strip().upper()

    material_id = (
        request.form.get("material_id")
        or None
    )

    familia_material_id = (
        request.form.get("familia_material_id")
        or None
    )

    cantidad_texto = (
        request.form.get("cantidad")
        or "1"
    )

    notas = (
        request.form.get("notas", "")
        .strip()
        or None
    )

    es_estimado = (
        1
        if request.form.get("es_estimado")
        else 0
    )

    try:

        if modo_seleccion not in {
            "EXACTO",
            "FAMILIA"
        }:
            raise ValueError(
                "La forma de seleccionar el material no es válida."
            )

        cantidad = Decimal(
            str(cantidad_texto)
        )

        if cantidad <= 0:
            raise ValueError(
                "La cantidad debe ser mayor que 0."
            )

        unidad_id = None

        if modo_seleccion == "EXACTO":

            if not material_id:
                raise ValueError(
                    "Debes seleccionar un material."
                )

            cursor.execute("""
                SELECT
                    id,
                    unidad_consumo_id
                FROM materiales
                WHERE id = %s
                  AND activo = 1
            """, (material_id,))

            material = cursor.fetchone()

            if not material:
                raise ValueError(
                    "El material seleccionado no existe."
                )

            unidad_id = material["unidad_consumo_id"]
            familia_material_id = None

            cursor.execute("""
                SELECT id
                FROM producto_materiales
                WHERE producto_id = %s
                  AND modo_seleccion = 'EXACTO'
                  AND material_id = %s
                LIMIT 1
            """, (
                producto_id,
                material_id
            ))

            if cursor.fetchone():
                raise ValueError(
                    "Ese material exacto ya está en la receta."
                )

        else:

            if not familia_material_id:
                raise ValueError(
                    "Debes seleccionar una familia de materiales."
                )

            cursor.execute("""
                SELECT id
                FROM familias_materiales
                WHERE id = %s
                  AND activo = 1
            """, (familia_material_id,))

            if not cursor.fetchone():
                raise ValueError(
                    "La familia seleccionada no existe."
                )

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM materiales
                WHERE familia_id = %s
                  AND activo = 1
            """, (familia_material_id,))

            if cursor.fetchone()["total"] <= 0:
                raise ValueError(
                    "Esa familia todavía no tiene materiales activos."
                )

            material_id = None
            unidad_id = None

            cursor.execute("""
                SELECT id
                FROM producto_materiales
                WHERE producto_id = %s
                  AND modo_seleccion = 'FAMILIA'
                  AND familia_material_id = %s
                LIMIT 1
            """, (
                producto_id,
                familia_material_id
            ))

            if cursor.fetchone():
                raise ValueError(
                    "Esa familia ya está agregada a la receta."
                )

        cursor.execute("""
            INSERT INTO producto_materiales
            (
                producto_id,
                material_id,
                familia_material_id,
                modo_seleccion,
                cantidad,
                unidad_id,
                es_estimado,
                notas
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
        """, (
            producto_id,
            material_id,
            familia_material_id,
            modo_seleccion,
            cantidad,
            unidad_id,
            es_estimado,
            notas
        ))

        conn.commit()

        flash(
            "Material agregado correctamente a la receta.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo agregar el material: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "materiales.materiales_producto",
            producto_id=producto_id
        )
    )


# ============================================================
# ELIMINAR MATERIAL DE LA RECETA
# ============================================================

@materiales_bp.route(
    "/producto/<int:producto_id>/eliminar/<int:receta_id>",
    methods=["POST"]
)
def eliminar_material_producto(
    producto_id,
    receta_id
):

    conn = obtener_conexion()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            DELETE FROM producto_materiales
            WHERE id = %s
              AND producto_id = %s
        """, (
            receta_id,
            producto_id
        ))

        conn.commit()

        flash(
            "Material eliminado de la receta.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo eliminar el material: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "materiales.materiales_producto",
            producto_id=producto_id
        )
    )