// SPDX-License-Identifier: Apache-2.0

pub const CONTRACT_SCHEMA: &str = "qsol.mesh.contract.v1";
pub const CONTRACT_VERSION: &str = "1.0.0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Command { Inspect, Calibrate, Plan, Run, Verify, Receipt }

impl Command {
    pub const ALL: [Self; 6] = [Self::Inspect, Self::Calibrate, Self::Plan, Self::Run, Self::Verify, Self::Receipt];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Inspect => "inspect",
            Self::Calibrate => "calibrate",
            Self::Plan => "plan",
            Self::Run => "run",
            Self::Verify => "verify",
            Self::Receipt => "receipt",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|command| command.as_str() == value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_surface_is_frozen_for_pr1() {
        let commands: Vec<_> = Command::ALL.into_iter().map(Command::as_str).collect();
        assert_eq!(commands, ["inspect", "calibrate", "plan", "run", "verify", "receipt"]);
    }

    #[test]
    fn parser_rejects_unknown_commands() {
        assert_eq!(Command::parse("inspect"), Some(Command::Inspect));
        assert_eq!(Command::parse("cuda"), None);
    }
}
