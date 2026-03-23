package com.omniagent.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.omniagent.app.ui.ChatViewModel
import com.omniagent.app.ui.screens.ChatScreen
import com.omniagent.app.ui.screens.DiscoveryScreen
import com.omniagent.app.ui.screens.LoginScreen
import com.omniagent.app.ui.theme.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            OmniAgentTheme {
                Box(modifier = Modifier
                    .fillMaxSize()
                    .windowInsetsPadding(WindowInsets.systemBars)
                    .imePadding()
                ) {
                    val vm: ChatViewModel = viewModel()
                    val state by vm.state.collectAsState()

                    when {
                        // Step 1: Connect to server
                        state.connectionState != "connected" -> DiscoveryScreen(state, vm)
                        // Step 2: Authenticate
                        state.authState == "checking" -> {
                            Surface(modifier = Modifier.fillMaxSize(), color = BgDark) {
                                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        CircularProgressIndicator(color = Accent)
                                        Spacer(Modifier.height(12.dp))
                                        Text("Checking authentication...", fontSize = 13.sp, color = TextDim)
                                    }
                                }
                            }
                        }
                        state.authState == "login" -> LoginScreen(state, vm)
                        // Step 3: Chat
                        else -> ChatScreen(vm)
                    }
                }
            }
        }
    }
}
