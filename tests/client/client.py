"""
Cliente MCP para Azure Calculator com Azure OpenAI
Utiliza o Agent Framework para processamento inteligente de consultas de preços
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from openai import AzureOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass
class AzureOpenAIConfig:
    """Configuração do Azure OpenAI"""
    endpoint: str
    api_key: str
    deployment_name: str
    api_version: str = "2024-02-15-preview"


class MCPAzureCalculatorClient:
    """Cliente que conecta MCP local com Azure OpenAI"""
    
    def __init__(self, azure_config: AzureOpenAIConfig, mcp_command: str, mcp_args: List[str] = None):
        """
        Inicializa o cliente
        
        Args:
            azure_config: Configuração do Azure OpenAI
            mcp_command: Comando para iniciar o servidor MCP (ex: "python")
            mcp_args: Argumentos do comando MCP (ex: ["mcp_server.py"])
        """
        self.azure_config = azure_config
        self.mcp_command = mcp_command
        self.mcp_args = mcp_args or []
        self.client: Optional[AzureOpenAI] = None
        self.mcp_session: Optional[ClientSession] = None
        self.mcp_exit_stack = None
        self.available_tools: List[Dict[str, Any]] = []
        
    async def connect_mcp(self):
        """Conecta ao servidor MCP local"""
        # Configuração do servidor MCP
        server_params = StdioServerParameters(
            command=self.mcp_command,
            args=self.mcp_args,
            env=None
        )
        
        # Usa o context manager corretamente
        mcp_context = stdio_client(server_params)
        stdio_transport = await mcp_context.__aenter__()
        self.mcp_exit_stack = mcp_context
        
        read_stream, write_stream = stdio_transport
        
        # Cria a sessão MCP
        self.mcp_session = ClientSession(read_stream, write_stream)
        await self.mcp_session.__aenter__()
        
        # Inicializa a sessão
        await self.mcp_session.initialize()
        
        # Lista as ferramentas disponíveis no MCP
        tools_result = await self.mcp_session.list_tools()
        self.available_tools = self._convert_mcp_tools_to_openai(tools_result.tools)
        
        print(f"✓ Conectado ao MCP. Ferramentas disponíveis: {len(self.available_tools)}")
        for tool in self.available_tools:
            print(f"  - {tool['function']['name']}: {tool['function']['description']}")
    
    def _convert_mcp_tools_to_openai(self, mcp_tools: List[Any]) -> List[Dict[str, Any]]:
        """Converte ferramentas MCP para formato OpenAI"""
        openai_tools = []
        
        for tool in mcp_tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
            openai_tools.append(openai_tool)
        
        return openai_tools
    
    def connect_azure_openai(self):
        """Conecta ao Azure OpenAI"""
        self.client = AzureOpenAI(
            api_key=self.azure_config.api_key,
            api_version=self.azure_config.api_version,
            azure_endpoint=self.azure_config.endpoint
        )
        print(f"✓ Conectado ao Azure OpenAI: {self.azure_config.endpoint}")
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Executa uma ferramenta do MCP"""
        if not self.mcp_session:
            raise RuntimeError("MCP não está conectado")
        
        print(f"\n🔧 Executando ferramenta MCP: {tool_name}")
        print(f"   Argumentos: {json.dumps(arguments, indent=2, ensure_ascii=False)}")
        
        result = await self.mcp_session.call_tool(tool_name, arguments)
        
        print(f"✓ Resultado recebido")
        return result
    
    async def process_query(self, user_query: str, max_iterations: int = 5) -> str:
        """
        Processa uma consulta do usuário usando o Agent Framework
        
        Args:
            user_query: Pergunta do usuário
            max_iterations: Número máximo de iterações agent-tool
            
        Returns:
            Resposta final do agente
        """
        if not self.client:
            raise RuntimeError("Azure OpenAI não está conectado")
        
        if not self.mcp_session:
            raise RuntimeError("MCP não está conectado")
        
        messages = [
            {
                "role": "system",
                "content": """Você é um assistente especializado em consultar preços de serviços do Azure.
                
Você tem acesso a ferramentas que permitem buscar preços no Azure Calculator.
Quando o usuário perguntar sobre preços, use as ferramentas disponíveis para obter informações precisas.

Sempre forneça respostas detalhadas incluindo:
- Nome do serviço
- Região
- Preço
- Unidade de medida
- Qualquer informação adicional relevante

Seja claro e objetivo nas respostas."""
            },
            {
                "role": "user",
                "content": user_query
            }
        ]
        
        print(f"\n💬 Consulta do usuário: {user_query}\n")
        
        for iteration in range(max_iterations):
            print(f"\n--- Iteração {iteration + 1} ---")
            
            # Chama o Azure OpenAI com as ferramentas disponíveis
            response = self.client.chat.completions.create(
                model=self.azure_config.deployment_name,
                messages=messages,
                tools=self.available_tools if self.available_tools else None,
                tool_choice="auto" if self.available_tools else None,
                temperature=0.7,
                max_tokens=2000
            )
            
            assistant_message = response.choices[0].message
            
            # Prepara a mensagem do assistente para o histórico
            assistant_msg = {
                "role": "assistant",
                "content": assistant_message.content
            }
            
            # Adiciona tool_calls se existirem
            if assistant_message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            
            messages.append(assistant_msg)
            
            # Se não há chamadas de ferramentas, retorna a resposta
            if not assistant_message.tool_calls:
                print("\n✓ Resposta final gerada")
                return assistant_message.content or "Sem resposta disponível."
            
            # Processa cada chamada de ferramenta
            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                try:
                    # Executa a ferramenta no MCP
                    tool_result = await self.call_mcp_tool(function_name, function_args)
                    
                    # Formata o resultado
                    if hasattr(tool_result, 'content'):
                        # Se content é uma lista, junta os textos
                        if isinstance(tool_result.content, list):
                            result_content = "\n".join([
                                item.text if hasattr(item, 'text') else str(item) 
                                for item in tool_result.content
                            ])
                        else:
                            result_content = str(tool_result.content)
                    else:
                        result_content = str(tool_result)
                    
                    # Adiciona o resultado ao histórico
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_content
                    })
                    
                except Exception as e:
                    error_msg = f"Erro ao executar ferramenta {function_name}: {str(e)}"
                    print(f"❌ {error_msg}")
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_msg
                    })
        
        return "Número máximo de iterações atingido. Não foi possível completar a consulta."
    
    async def close(self):
        """Fecha as conexões"""
        try:
            if self.mcp_session:
                await self.mcp_session.__aexit__(None, None, None)
                
            if self.mcp_exit_stack:
                await self.mcp_exit_stack.__aexit__(None, None, None)
                
            print("\n✓ Conexão MCP fechada")
        except Exception as e:
            print(f"Erro ao fechar conexões: {e}")


async def main():
    """Função principal - exemplo de uso"""
    
    # Configuração do Azure OpenAI
    # IMPORTANTE: Configure estas variáveis de ambiente ou substitua diretamente
    azure_config = AzureOpenAIConfig(
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "https://seu-recurso.openai.azure.com/"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY", "sua-chave-aqui"),
        deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4"),
        api_version="2024-02-15-preview"
    )
    
    # Comando para iniciar seu servidor MCP local
    # Ajuste conforme necessário
    mcp_command = "python"
    mcp_args = ["azure_calculator_mcp_server.py"]
    
    # Alternativa para Node.js:
    # mcp_command = "node"
    # mcp_args = ["server.js"]
    
    # Cria o cliente
    client = MCPAzureCalculatorClient(azure_config, mcp_command, mcp_args)
    
    try:
        # Conecta ao MCP e Azure OpenAI
        print("🚀 Iniciando cliente MCP com Azure OpenAI...\n")
        await client.connect_mcp()
        client.connect_azure_openai()
        
        # Modo interativo
        print("\n" + "="*60)
        print("Cliente MCP Azure Calculator - Modo Interativo")
        print("="*60)
        print("Digite 'sair' para encerrar\n")
        
        while True:
            user_input = input("\n💬 Sua pergunta: ").strip()
            
            if user_input.lower() in ['sair', 'exit', 'quit']:
                print("\n👋 Encerrando...")
                break
            
            if not user_input:
                continue
            
            # Processa a consulta
            response = await client.process_query(user_input)
            
            print("\n" + "="*60)
            print("🤖 Resposta:")
            print("="*60)
            print(response)
            print("="*60)
    
    except KeyboardInterrupt:
        print("\n\n👋 Interrompido pelo usuário")
    
    except Exception as e:
        print(f"\n❌ Erro: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())