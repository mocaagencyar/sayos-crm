# tests/test_local.py — Simulador de chat con Max en terminal
# Generado por AgentKit

"""
Probá a Max sin necesitar WhatsApp.
Simula una conversación en la terminal como si fueras un prospecto.
"""

import asyncio
import sys
import os

# Agregar el directorio raíz al path para importar el agente
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, limpiar_historial
from agent.tools import cargar_info_negocio

# Número de teléfono ficticio para el test
TELEFONO_TEST = "test-local-001"


async def main():
    """Loop principal del chat de prueba con Max."""
    await inicializar_db()

    print()
    print("=" * 60)
    print("   AgentKit — Test Local | Agente: Max")
    print(f"   Negocio: {cargar_info_negocio().get('negocio', {}).get('nombre', 'No configurado')}")
    print("=" * 60)
    print()
    print("  Escribí mensajes como si fueras un prospecto del negocio.")
    print("  Comandos especiales:")
    print("    'limpiar'  — borra el historial (nueva conversación)")
    print("    'salir'    — termina el test")
    print()
    print("-" * 60)
    print()

    while True:
        try:
            mensaje = input("Prospecto: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest finalizado. ¡Hasta pronto!")
            break

        if not mensaje:
            continue

        if mensaje.lower() == "salir":
            print("\nTest finalizado. ¡Hasta pronto!")
            break

        if mensaje.lower() == "limpiar":
            await limpiar_historial(TELEFONO_TEST)
            print("[Historial borrado — nueva conversación]\n")
            continue

        # Obtener historial ANTES de guardar el mensaje actual
        historial = await obtener_historial(TELEFONO_TEST)

        # Generar respuesta con Max
        print("\nMax: ", end="", flush=True)
        respuesta = await generar_respuesta(mensaje, historial)
        print(respuesta)
        print()

        # Guardar mensaje del prospecto y respuesta de Max en memoria
        await guardar_mensaje(TELEFONO_TEST, "user", mensaje)
        await guardar_mensaje(TELEFONO_TEST, "assistant", respuesta)


if __name__ == "__main__":
    asyncio.run(main())
